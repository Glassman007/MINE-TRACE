from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.core.settings import Settings
from app.integrations.embeddings import (
    EmbeddingBatchError,
    EmbeddingInputError,
    EmbeddingKind,
    EmbeddingProviderUnavailableError,
    EmbeddingTimeoutError,
    InvalidEmbeddingError,
    QDRANT_CLOUD_INFERENCE_PROVIDER,
    QdrantCloudInferenceEmbeddingProvider,
    build_embedding_provider,
)


class FakeCloudInferenceClient:
    def __init__(self) -> None:
        self.document_calls: list[dict[str, object]] = []
        self.query_calls: list[dict[str, object]] = []
        self.document_vectors: Sequence[Sequence[float]] = ((0.1, 0.2, 0.3),)
        self.query_vectors: Sequence[Sequence[float]] = ((0.4, 0.5, 0.6),)
        self.document_error: Exception | None = None
        self.query_error: Exception | None = None

    def embed_documents(self, *, texts, model, timeout_seconds):
        self.document_calls.append(
            {"texts": tuple(texts), "model": model, "timeout_seconds": timeout_seconds}
        )
        if self.document_error is not None:
            raise self.document_error
        return self.document_vectors

    def embed_queries(self, *, texts, model, timeout_seconds):
        self.query_calls.append(
            {"texts": tuple(texts), "model": model, "timeout_seconds": timeout_seconds}
        )
        if self.query_error is not None:
            raise self.query_error
        return self.query_vectors


def _provider(client: FakeCloudInferenceClient | None = None):
    return QdrantCloudInferenceEmbeddingProvider(
        model="sentence-transformers/all-minilm-l6-v2",
        timeout_seconds=7.5,
        client=client,
    )


def test_single_document_embedding_is_typed_and_dimension_is_discovered_from_result() -> None:
    client = FakeCloudInferenceClient()
    vector = _provider(client).embed_document("  pump   whine under load  ")

    assert vector.values == (0.1, 0.2, 0.3)
    assert vector.dimensions == 3
    assert vector.kind is EmbeddingKind.DOCUMENT
    assert vector.provider == QDRANT_CLOUD_INFERENCE_PROVIDER
    assert vector.model == "sentence-transformers/all-minilm-l6-v2"
    assert client.document_calls == [
        {
            "texts": ("pump whine under load",),
            "model": "sentence-transformers/all-minilm-l6-v2",
            "timeout_seconds": 7.5,
        }
    ]


def test_query_embedding_uses_distinct_provider_operation() -> None:
    client = FakeCloudInferenceClient()
    vector = _provider(client).embed_query("similar pump noise")

    assert vector.values == (0.4, 0.5, 0.6)
    assert vector.kind is EmbeddingKind.QUERY
    assert client.document_calls == []
    assert len(client.query_calls) == 1


def test_batch_document_embedding_preserves_order_and_discovers_dimensions() -> None:
    client = FakeCloudInferenceClient()
    client.document_vectors = ((1.0, 2.0), (3.0, 4.0))

    vectors = _provider(client).embed_documents(("first note", "second note"))

    assert [vector.values for vector in vectors] == [(1.0, 2.0), (3.0, 4.0)]
    assert all(vector.dimensions == 2 for vector in vectors)


def test_empty_or_invalid_semantic_text_is_rejected_before_provider_call() -> None:
    client = FakeCloudInferenceClient()
    provider = _provider(client)

    with pytest.raises(EmbeddingInputError):
        provider.embed_document("  \n\t ")
    with pytest.raises(EmbeddingInputError):
        provider.embed_query("")
    with pytest.raises(EmbeddingInputError):
        provider.embed_documents(("valid", "   "))

    assert client.document_calls == []
    assert client.query_calls == []


def test_provider_unavailable_is_explicit() -> None:
    provider = _provider(None)

    with pytest.raises(EmbeddingProviderUnavailableError):
        provider.embed_document("pump whine")


def test_timeout_is_mapped_without_retrying_or_mutating_other_state() -> None:
    client = FakeCloudInferenceClient()
    client.query_error = TimeoutError("network timeout")

    with pytest.raises(EmbeddingTimeoutError):
        _provider(client).embed_query("pump whine")

    assert len(client.query_calls) == 1


def test_batch_provider_failure_is_explicit() -> None:
    client = FakeCloudInferenceClient()
    client.document_error = RuntimeError("provider unavailable")

    with pytest.raises(EmbeddingBatchError):
        _provider(client).embed_documents(("one", "two"))


def test_malformed_vectors_are_rejected_without_hardcoded_dimension() -> None:
    client = FakeCloudInferenceClient()
    client.document_vectors = ((1.0, 2.0), (3.0, 4.0, 5.0))

    with pytest.raises(InvalidEmbeddingError):
        _provider(client).embed_documents(("one", "two"))


def test_configured_provider_factory_selects_qdrant_cloud_without_connecting() -> None:
    settings = Settings(
        environment="test",
        embedding_provider="qdrant_cloud_inference",
        embedding_model="sentence-transformers/all-minilm-l6-v2",
        qdrant_timeout_seconds=6,
    )
    client = FakeCloudInferenceClient()

    provider = build_embedding_provider(settings, qdrant_cloud_client=client)
    vector = provider.embed_document("operator reported grinding noise")

    assert vector.model == "sentence-transformers/all-minilm-l6-v2"
    assert client.document_calls[0]["timeout_seconds"] == 6
