"""Qdrant Cloud Inference embedding adapter.

Qdrant Cloud's documented Python API normally performs remote inference while
upserting/querying ``models.Document`` values. It does not expose a stable
standalone public method that returns raw vectors independent of a Qdrant
operation. This adapter therefore isolates materialization behind an injected
client contract instead of relying on an undocumented endpoint.

A concrete network transport can be connected in the later Qdrant integration
step without changing semantic-document or provider-facing contracts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.integrations.embeddings.base import (
    EmbeddingBatchError,
    EmbeddingKind,
    EmbeddingProviderUnavailableError,
    EmbeddingTimeoutError,
    EmbeddingVector,
    InvalidEmbeddingError,
    validate_embedding_text,
)

QDRANT_CLOUD_INFERENCE_PROVIDER = "qdrant_cloud_inference"


class QdrantCloudInferenceClient(Protocol):
    """Narrow transport contract for raw dense-vector inference.

    This is intentionally smaller than QdrantClient and has no collection,
    incident, evidence, or canonical mutation methods.
    """

    def embed_documents(
        self,
        *,
        texts: Sequence[str],
        model: str,
        timeout_seconds: float,
    ) -> Sequence[Sequence[float]]: ...

    def embed_queries(
        self,
        *,
        texts: Sequence[str],
        model: str,
        timeout_seconds: float,
    ) -> Sequence[Sequence[float]]: ...


class QdrantCloudInferenceEmbeddingProvider:
    """Dense embedding provider backed by a Qdrant Cloud inference transport.

    Construction itself performs no network request. The transport is injected
    so this layer can be tested without external services and without inventing
    an undocumented Qdrant endpoint.
    """

    provider_name = QDRANT_CLOUD_INFERENCE_PROVIDER

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        client: QdrantCloudInferenceClient | None,
        observability: MLAIObservability | None = None,
    ) -> None:
        model = model.strip()
        if not model:
            raise EmbeddingProviderUnavailableError("embedding model is not configured")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._model = model
        self._timeout_seconds = float(timeout_seconds)
        self._client = client
        self._observability = observability or get_ml_ai_observability()

    @property
    def model(self) -> str:
        return self._model

    def embed_document(self, text: str) -> EmbeddingVector:
        return self.embed_documents((text,))[0]

    def embed_query(self, text: str) -> EmbeddingVector:
        normalized = validate_embedding_text(text)
        client = self._require_client()
        try:
            raw = client.embed_queries(
                texts=(normalized,),
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            )
            vectors = self._validate_batch(raw, expected_count=1, kind=EmbeddingKind.QUERY)
        except TimeoutError as exc:
            self._record_failure("embedding_timeout")
            raise EmbeddingTimeoutError("Qdrant Cloud query embedding timed out") from exc
        except EmbeddingTimeoutError:
            self._record_failure("embedding_timeout")
            raise
        except InvalidEmbeddingError:
            self._record_failure("invalid_embedding")
            raise
        except Exception as exc:
            self._record_failure("embedding_provider_unavailable")
            raise EmbeddingProviderUnavailableError(
                "Qdrant Cloud query embedding is unavailable"
            ) from exc

        self._record_success()
        return vectors[0]

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes, bytearray)):
            raise TypeError("texts must be a sequence of strings")
        if not texts:
            raise EmbeddingBatchError("embedding batch must not be empty")

        normalized = tuple(validate_embedding_text(text) for text in texts)
        client = self._require_client()
        try:
            raw = client.embed_documents(
                texts=normalized,
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            )
            vectors = self._validate_batch(
                raw,
                expected_count=len(normalized),
                kind=EmbeddingKind.DOCUMENT,
            )
        except TimeoutError as exc:
            self._record_failure("embedding_timeout")
            raise EmbeddingTimeoutError("Qdrant Cloud document embedding timed out") from exc
        except EmbeddingTimeoutError:
            self._record_failure("embedding_timeout")
            raise
        except (EmbeddingBatchError, InvalidEmbeddingError):
            self._record_failure("invalid_embedding_batch")
            raise
        except Exception as exc:
            self._record_failure("embedding_batch_failed")
            raise EmbeddingBatchError("Qdrant Cloud document embedding batch failed") from exc

        self._record_success()
        return vectors


    def probe_availability(self) -> bool:
        """Verify inference with a synthetic query; no canonical text is sent."""

        try:
            self.embed_query("MINE-TRACE operational capability probe")
        except Exception:
            return False
        return True

    def _record_success(self) -> None:
        self._observability.record_embedding_success()
        self._observability.record_capability(
            "embedding_provider", CapabilityStatus.AVAILABLE, "embedding_succeeded"
        )

    def _record_failure(self, reason: str) -> None:
        self._observability.record_embedding_failure()
        self._observability.record_capability(
            "embedding_provider", CapabilityStatus.UNAVAILABLE, reason
        )

    def _require_client(self) -> QdrantCloudInferenceClient:
        if self._client is None:
            self._record_failure("embedding_transport_not_connected")
            raise EmbeddingProviderUnavailableError(
                "Qdrant Cloud inference transport is not connected"
            )
        return self._client

    def _validate_batch(
        self,
        raw_vectors: Sequence[Sequence[float]],
        *,
        expected_count: int,
        kind: EmbeddingKind,
    ) -> tuple[EmbeddingVector, ...]:
        if len(raw_vectors) != expected_count:
            raise EmbeddingBatchError(
                f"embedding provider returned {len(raw_vectors)} vectors for "
                f"{expected_count} inputs"
            )

        vectors = tuple(
            EmbeddingVector.validated(
                raw,
                provider=self.provider_name,
                model=self._model,
                kind=kind,
            )
            for raw in raw_vectors
        )

        # No global/model dimension is hardcoded. We only require one provider
        # response batch to be internally consistent.
        dimensions = {vector.dimensions for vector in vectors}
        if len(dimensions) != 1:
            raise InvalidEmbeddingError(
                "embedding provider returned inconsistent vector dimensions in one batch"
            )
        return vectors
