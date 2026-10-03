"""Local FastEmbed dense-embedding provider.

This adapter keeps semantic retrieval inside the existing provider abstraction:
canonical PostgreSQL text -> local FastEmbed -> disposable Qdrant vectors.
The model object is constructed once per provider lifecycle and reused across
all document/query calls. FastEmbed may download model files on first use; once
cached, inference itself does not require a paid API or network service.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.integrations.embeddings.base import (
    EmbeddingBatchError,
    EmbeddingKind,
    EmbeddingProviderUnavailableError,
    EmbeddingVector,
    InvalidEmbeddingError,
    validate_embedding_text,
)

FASTEMBED_PROVIDER = "fastembed"
DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_FASTEMBED_DIMENSION = 384


class FastEmbedModel(Protocol):
    """Narrow subset of ``fastembed.TextEmbedding`` used by the adapter."""

    @property
    def embedding_size(self) -> int: ...

    def passage_embed(self, texts: Iterable[str], **kwargs: Any) -> Iterable[Any]: ...

    def query_embed(self, texts: str | Iterable[str], **kwargs: Any) -> Iterable[Any]: ...


class FastEmbedEmbeddingProvider:
    """Dense embeddings produced locally through one reusable FastEmbed model."""

    provider_name = FASTEMBED_PROVIDER

    def __init__(
        self,
        *,
        model: str = DEFAULT_FASTEMBED_MODEL,
        expected_dimension: int = DEFAULT_FASTEMBED_DIMENSION,
        model_instance: FastEmbedModel | None = None,
        batch_size: int = 256,
        observability: MLAIObservability | None = None,
    ) -> None:
        model = model.strip()
        if not model:
            raise EmbeddingProviderUnavailableError("embedding model is not configured")
        if expected_dimension <= 0:
            raise ValueError("expected_dimension must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        self._model_name = model
        self._expected_dimension = int(expected_dimension)
        self._batch_size = int(batch_size)
        self._observability = observability or get_ml_ai_observability()

        try:
            self._model = model_instance or self._load_model(model)
            actual_dimension = int(self._model.embedding_size)
        except EmbeddingProviderUnavailableError:
            self._record_failure("embedding_model_initialization_failed")
            raise
        except Exception as exc:
            self._record_failure("embedding_model_initialization_failed")
            raise EmbeddingProviderUnavailableError(
                f"FastEmbed model initialization failed for {model}"
            ) from exc

        if actual_dimension != self._expected_dimension:
            self._record_failure("embedding_dimension_mismatch")
            raise EmbeddingProviderUnavailableError(
                "FastEmbed model dimension mismatch: "
                f"configured={self._expected_dimension}, model={actual_dimension}"
            )

    @staticmethod
    def _load_model(model: str) -> FastEmbedModel:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingProviderUnavailableError(
                "FastEmbed runtime dependency is unavailable"
            ) from exc
        try:
            return TextEmbedding(model_name=model)
        except Exception as exc:
            raise EmbeddingProviderUnavailableError(
                f"FastEmbed model initialization failed for {model}"
            ) from exc

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    def embed_document(self, text: str) -> EmbeddingVector:
        return self.embed_documents((text,))[0]

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes, bytearray)):
            raise TypeError("texts must be a sequence of strings")
        if not texts:
            raise EmbeddingBatchError("embedding batch must not be empty")

        normalized = tuple(validate_embedding_text(text) for text in texts)
        try:
            raw_vectors = tuple(
                self._model.passage_embed(normalized, batch_size=self._batch_size)
            )
            vectors = self._validate_batch(
                raw_vectors,
                expected_count=len(normalized),
                kind=EmbeddingKind.DOCUMENT,
            )
        except (EmbeddingBatchError, InvalidEmbeddingError):
            self._record_failure("invalid_embedding_batch")
            raise
        except Exception as exc:
            self._record_failure("embedding_batch_failed")
            raise EmbeddingBatchError("FastEmbed document embedding batch failed") from exc

        self._record_success()
        return vectors

    def embed_query(self, text: str) -> EmbeddingVector:
        normalized = validate_embedding_text(text)
        try:
            raw_vectors = tuple(self._model.query_embed((normalized,)))
            vectors = self._validate_batch(
                raw_vectors,
                expected_count=1,
                kind=EmbeddingKind.QUERY,
            )
        except InvalidEmbeddingError:
            self._record_failure("invalid_embedding")
            raise
        except Exception as exc:
            self._record_failure("embedding_provider_unavailable")
            raise EmbeddingProviderUnavailableError(
                "FastEmbed query embedding is unavailable"
            ) from exc

        self._record_success()
        return vectors[0]

    def probe_availability(self) -> bool:
        """Verify local inference without sending canonical/user data anywhere."""

        try:
            self.embed_query("MINE-TRACE operational capability probe")
        except Exception:
            return False
        return True

    def _validate_batch(
        self,
        raw_vectors: Sequence[Any],
        *,
        expected_count: int,
        kind: EmbeddingKind,
    ) -> tuple[EmbeddingVector, ...]:
        if len(raw_vectors) != expected_count:
            raise EmbeddingBatchError(
                f"FastEmbed returned {len(raw_vectors)} vectors for {expected_count} inputs"
            )

        vectors = tuple(
            EmbeddingVector.validated(
                raw,
                provider=self.provider_name,
                model=self._model_name,
                kind=kind,
            )
            for raw in raw_vectors
        )
        dimensions = {vector.dimensions for vector in vectors}
        if dimensions != {self._expected_dimension}:
            raise InvalidEmbeddingError(
                "FastEmbed returned an unexpected vector dimension: "
                f"expected={self._expected_dimension}, actual={sorted(dimensions)}"
            )
        return vectors

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
