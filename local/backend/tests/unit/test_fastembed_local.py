from __future__ import annotations

import sys
import types

import pytest

from app.integrations.embeddings.base import EmbeddingKind, EmbeddingProviderUnavailableError, InvalidEmbeddingError
from app.integrations.embeddings.fastembed_local import (
    PINNED_DIMENSION,
    PINNED_MODEL,
    FastEmbedLocalEmbeddingProvider,
)


class _FakeModel:
    def passage_embed(self, texts):
        return ([float(i % 7) for i in range(PINNED_DIMENSION)] for _ in texts)

    def query_embed(self, texts):
        return ([float((i + 1) % 5) for i in range(PINNED_DIMENSION)] for _ in texts)


def test_offline_provider_embeds_documents_and_queries_with_pinned_dimension() -> None:
    provider = FastEmbedLocalEmbeddingProvider(
        model=PINNED_MODEL,
        cache_location="/preloaded/model/cache",
        expected_dimension=PINNED_DIMENSION,
        model_factory=lambda **_: _FakeModel(),
    )
    document = provider.embed_document("hydraulic hose inspection note")
    query = provider.embed_query("similar hydraulic hose issue")
    batch = provider.embed_documents(("one", "two"))

    assert document.kind is EmbeddingKind.DOCUMENT
    assert query.kind is EmbeddingKind.QUERY
    assert document.dimensions == query.dimensions == PINNED_DIMENSION
    assert [item.dimensions for item in batch] == [PINNED_DIMENSION, PINNED_DIMENSION]


def test_default_runtime_loader_forces_local_files_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeTextEmbedding(_FakeModel):
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))
    provider = FastEmbedLocalEmbeddingProvider(
        model=PINNED_MODEL,
        cache_location="/edge/cache",
        expected_dimension=PINNED_DIMENSION,
    )
    assert provider.embed_query("offline probe").dimensions == PINNED_DIMENSION
    assert captured["model_name"] == PINNED_MODEL
    assert captured["cache_dir"] == "/edge/cache"
    assert captured["local_files_only"] is True


def test_missing_local_model_degrades_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingTextEmbedding:
        def __init__(self, **kwargs):
            assert kwargs["local_files_only"] is True
            raise FileNotFoundError("model absent")

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=MissingTextEmbedding))
    with pytest.raises(EmbeddingProviderUnavailableError):
        FastEmbedLocalEmbeddingProvider(
            model=PINNED_MODEL,
            cache_location="/missing/cache",
            expected_dimension=PINNED_DIMENSION,
        )


def test_dimension_mismatch_is_rejected() -> None:
    class WrongDimensionModel:
        def query_embed(self, texts):
            return ([0.0] * 12 for _ in texts)

    provider = FastEmbedLocalEmbeddingProvider(
        model=PINNED_MODEL,
        cache_location="/cache",
        expected_dimension=PINNED_DIMENSION,
        model_factory=lambda **_: WrongDimensionModel(),
    )
    with pytest.raises(InvalidEmbeddingError):
        provider.embed_query("dimension check")
