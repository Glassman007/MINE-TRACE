from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.logging import JsonFormatter
from app.core.ml_ai_observability import MLAIObservability
from app.integrations.embeddings import EmbeddingProviderUnavailableError
from app.integrations.embeddings.qdrant_cloud import QdrantCloudInferenceEmbeddingProvider
from app.integrations.qdrant import QdrantAvailability, QdrantService


class FakeDistance:
    COSINE = "Cosine"
    DOT = "Dot"
    EUCLID = "Euclid"
    MANHATTAN = "Manhattan"


class FakeMatchValue:
    def __init__(self, *, value: str) -> None:
        self.value = value


class FakeFieldCondition:
    def __init__(self, *, key: str, match: object) -> None:
        self.key = key
        self.match = match


class FakeFilter:
    def __init__(self, *, must: list[object]) -> None:
        self.must = must


class FakeModels:
    Distance = FakeDistance
    MatchValue = FakeMatchValue
    FieldCondition = FakeFieldCondition
    Filter = FakeFilter


class SearchClient:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def get_collections(self):
        if not self.available:
            raise ConnectionError("offline")
        return SimpleNamespace(collections=[SimpleNamespace(name="mine_trace_evidence")])

    def query_points(self, **kwargs):
        del kwargs
        if not self.available:
            raise ConnectionError("offline")
        return SimpleNamespace(points=[])


class FailedInferenceClient:
    def embed_queries(self, **kwargs):
        del kwargs
        raise ConnectionError("provider offline")

    def embed_documents(self, **kwargs):
        del kwargs
        raise ConnectionError("provider offline")


def test_qdrant_connectivity_and_search_latency_are_observed() -> None:
    observer = MLAIObservability()
    client = SearchClient()
    qdrant = QdrantService(
        collection_name="mine_trace_evidence",
        client=client,
        models_module=FakeModels,
        observability=observer,
    )

    assert qdrant.connectivity().availability is QdrantAvailability.AVAILABLE
    result = qdrant.vector_search(vector=[0.1, 0.2], top_k=5)
    assert result.availability is QdrantAvailability.AVAILABLE

    snapshot = observer.snapshot()
    assert snapshot.qdrant_search_count == 1
    assert snapshot.qdrant_search_failures == 0
    assert snapshot.last_qdrant_search_latency_ms is not None

    client.available = False
    assert qdrant.connectivity().availability is QdrantAvailability.UNAVAILABLE
    failed = qdrant.vector_search(vector=[0.1, 0.2], top_k=5)
    assert failed.availability is QdrantAvailability.UNAVAILABLE
    snapshot = observer.snapshot()
    assert snapshot.qdrant_connectivity_failures >= 2
    assert snapshot.qdrant_search_failures == 1


def test_embedding_provider_failure_is_observed_without_payload_capture() -> None:
    observer = MLAIObservability()
    provider = QdrantCloudInferenceEmbeddingProvider(
        model="sentence-transformers/all-minilm-l6-v2",
        timeout_seconds=1,
        client=FailedInferenceClient(),
        observability=observer,
    )

    with pytest.raises(EmbeddingProviderUnavailableError):
        provider.embed_query("synthetic operational text")

    snapshot = observer.snapshot()
    assert snapshot.embedding_provider_failures == 1


def test_operational_recorder_counts_stale_indexing_and_fallback_signals() -> None:
    observer = MLAIObservability()
    observer.record_stale_qdrant_reference(2)
    observer.record_indexing_failure(3)
    observer.record_fallback("AI_TIMEOUT")
    observer.record_fallback("AI_TIMEOUT")

    snapshot = observer.snapshot()
    assert snapshot.stale_qdrant_reference_count == 2
    assert snapshot.indexing_failures == 3
    assert snapshot.fallback_reasons == {"AI_TIMEOUT": 2}


def test_json_logging_redacts_secrets_headers_and_sensitive_payload_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="operational_event",
        args=(),
        exc_info=None,
    )
    record.api_key = "super-secret"
    record.authorization = "Bearer token"
    record.canonical_payload = {"note": "private evidence text"}
    record.provenance = {"source": "sensitive"}
    record.safe_reason = "provider_timeout"

    rendered = json.loads(JsonFormatter().format(record))
    context = rendered["context"]
    assert context["api_key"] == "[REDACTED]"
    assert context["authorization"] == "[REDACTED]"
    assert context["canonical_payload"] == "[REDACTED]"
    assert context["provenance"] == "[REDACTED]"
    assert context["safe_reason"] == "provider_timeout"
    assert "super-secret" not in json.dumps(rendered)
    assert "private evidence text" not in json.dumps(rendered)
