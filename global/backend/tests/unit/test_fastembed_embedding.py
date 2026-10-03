from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.integrations.embeddings import (
    DEFAULT_FASTEMBED_DIMENSION,
    DEFAULT_FASTEMBED_MODEL,
    FASTEMBED_PROVIDER,
    EmbeddingKind,
    EmbeddingProviderUnavailableError,
    FastEmbedEmbeddingProvider,
    build_embedding_provider,
)
from app.integrations.qdrant import QdrantAvailability, QdrantDistance, QdrantService


class FakeFastEmbedModel:
    def __init__(self, *, dimension: int = 384) -> None:
        self.embedding_size = dimension
        self.passage_calls: list[tuple[str, ...]] = []
        self.query_calls: list[tuple[str, ...]] = []

    def _vector(self, text: str) -> tuple[float, ...]:
        seed = float((sum(ord(char) for char in text) % 97) + 1)
        return tuple(seed + (index / 1000.0) for index in range(self.embedding_size))

    def passage_embed(self, texts, **kwargs):
        del kwargs
        materialized = tuple(texts)
        self.passage_calls.append(materialized)
        return (self._vector(text) for text in materialized)

    def query_embed(self, texts, **kwargs):
        del kwargs
        materialized = (texts,) if isinstance(texts, str) else tuple(texts)
        self.query_calls.append(materialized)
        return (self._vector(text) for text in materialized)


class FakeDistance:
    COSINE = "COSINE"
    DOT = "DOT"
    EUCLID = "EUCLID"
    MANHATTAN = "MANHATTAN"


class FakeVectorParams:
    def __init__(self, *, size: int, distance: str) -> None:
        self.size = size
        self.distance = distance


class FakeQdrantModels:
    Distance = FakeDistance
    VectorParams = FakeVectorParams


class FakeQdrantClient:
    def __init__(self, *, existing_dimension: int | None = None) -> None:
        self.dimension = existing_dimension
        self.distance = FakeDistance.COSINE
        self.created: list[dict[str, object]] = []

    def collection_exists(self, *, collection_name: str) -> bool:
        del collection_name
        return self.dimension is not None

    def create_collection(self, **kwargs) -> None:
        params = kwargs["vectors_config"]
        self.dimension = params.size
        self.distance = params.distance
        self.created.append(kwargs)

    def get_collection(self, *, collection_name: str):
        del collection_name
        vectors = SimpleNamespace(size=self.dimension, distance=self.distance)
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=vectors))
        )


def test_fastembed_is_default_local_embedding_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_provider == FASTEMBED_PROVIDER
    assert settings.embedding_model == DEFAULT_FASTEMBED_MODEL
    assert settings.embedding_dimension == DEFAULT_FASTEMBED_DIMENSION == 384
    assert settings.embedding_api_key is None


def test_local_document_and_query_embeddings_use_same_384_dimension() -> None:
    model = FakeFastEmbedModel(dimension=384)
    provider = FastEmbedEmbeddingProvider(
        model=DEFAULT_FASTEMBED_MODEL,
        expected_dimension=384,
        model_instance=model,
    )

    documents = provider.embed_documents(("operator saw brake dust", "technician replaced pad"))
    query = provider.embed_query("similar brake wear")

    assert len(documents) == 2
    assert all(vector.kind is EmbeddingKind.DOCUMENT for vector in documents)
    assert query.kind is EmbeddingKind.QUERY
    assert all(vector.dimensions == 384 for vector in (*documents, query))
    assert all(vector.model == DEFAULT_FASTEMBED_MODEL for vector in (*documents, query))
    assert all(vector.provider == FASTEMBED_PROVIDER for vector in (*documents, query))
    assert model.passage_calls == [
        ("operator saw brake dust", "technician replaced pad")
    ]
    assert model.query_calls == [("similar brake wear",)]


def test_provider_factory_selects_fastembed_without_api_key() -> None:
    model = FakeFastEmbedModel(dimension=384)
    settings = Settings(
        _env_file=None,
        embedding_provider="fastembed",
        embedding_model=DEFAULT_FASTEMBED_MODEL,
        embedding_dimension=384,
        embedding_api_key=None,
    )

    provider = build_embedding_provider(settings, fastembed_model=model)
    vector = provider.embed_document("local semantic text")

    assert vector.dimensions == 384
    assert vector.provider == FASTEMBED_PROVIDER


def test_fastembed_model_dimension_mismatch_fails_clearly() -> None:
    with pytest.raises(EmbeddingProviderUnavailableError, match="dimension mismatch"):
        FastEmbedEmbeddingProvider(
            model=DEFAULT_FASTEMBED_MODEL,
            expected_dimension=384,
            model_instance=FakeFastEmbedModel(dimension=768),
        )


def test_fastembed_model_is_loaded_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeFastEmbedModel(dimension=384)
    loads: list[str] = []

    def fake_load(model_name: str):
        loads.append(model_name)
        return model

    monkeypatch.setattr(FastEmbedEmbeddingProvider, "_load_model", staticmethod(fake_load))
    provider = FastEmbedEmbeddingProvider(
        model=DEFAULT_FASTEMBED_MODEL,
        expected_dimension=384,
    )

    provider.embed_document("first document")
    provider.embed_document("second document")
    provider.embed_query("one query")

    assert loads == [DEFAULT_FASTEMBED_MODEL]
    assert len(model.passage_calls) == 2
    assert len(model.query_calls) == 1


def test_qdrant_collection_is_created_with_fastembed_dimension() -> None:
    client = FakeQdrantClient()
    qdrant = QdrantService(
        collection_name="mine_trace_evidence",
        distance=QdrantDistance.COSINE,
        client=client,
        models_module=FakeQdrantModels,
    )

    result = qdrant.initialize_collection(vector_size=384)

    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.compatible is True
    assert result.actual_vector_size == 384
    assert client.dimension == 384


def test_qdrant_does_not_silently_reuse_wrong_dimension_collection() -> None:
    client = FakeQdrantClient(existing_dimension=768)
    qdrant = QdrantService(
        collection_name="mine_trace_evidence",
        distance=QdrantDistance.COSINE,
        client=client,
        models_module=FakeQdrantModels,
    )

    result = qdrant.initialize_collection(vector_size=384)

    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.compatible is False
    assert result.actual_vector_size == 768
    assert "vector_size_mismatch" in (result.reason or "")
    assert client.created == []


def test_fastembed_initialization_failure_is_reported_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = MLAIObservability()

    def fail_load(model_name: str):
        raise RuntimeError(f"model unavailable: {model_name}")

    monkeypatch.setattr(FastEmbedEmbeddingProvider, "_load_model", staticmethod(fail_load))

    with pytest.raises(EmbeddingProviderUnavailableError, match="initialization failed"):
        FastEmbedEmbeddingProvider(
            model=DEFAULT_FASTEMBED_MODEL,
            expected_dimension=384,
            observability=observability,
        )

    snapshot = observability.snapshot()
    assert snapshot.embedding_provider_failures == 1
