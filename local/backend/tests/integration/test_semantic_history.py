from __future__ import annotations

from collections.abc import Generator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.integrations.embeddings import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant import QdrantService
from app.models import ComponentRecord, EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_history import SemanticHistoryFailure
from app.services.semantic_history import SemanticHistoryService


class FakeEmbeddingProvider:
    def __init__(
        self,
        *,
        query_vector: Sequence[float] = (0.1, 0.2),
        document_vector: Sequence[float] = (0.2, 0.3),
        query_error: Exception | None = None,
        document_error: Exception | None = None,
    ) -> None:
        self.query_vector = tuple(query_vector)
        self.document_vector = tuple(document_vector)
        self.query_error = query_error
        self.document_error = document_error
        self.query_texts: list[str] = []
        self.document_texts: list[str] = []

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_texts.append(text)
        if self.query_error is not None:
            raise self.query_error
        return EmbeddingVector.validated(
            self.query_vector,
            provider="fake",
            model="fake-model",
            kind=EmbeddingKind.QUERY,
        )

    def embed_document(self, text: str) -> EmbeddingVector:
        self.document_texts.append(text)
        if self.document_error is not None:
            raise self.document_error
        return EmbeddingVector.validated(
            self.document_vector,
            provider="fake",
            model="fake-model",
            kind=EmbeddingKind.DOCUMENT,
        )

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        return tuple(self.embed_document(text) for text in texts)




class FakePointStruct:
    def __init__(self, *, id: str, vector: list[float], payload: dict[str, str]) -> None:
        self.id = id
        self.vector = vector
        self.payload = payload


class FakeMatchValue:
    def __init__(self, *, value: str) -> None:
        self.value = value


class FakeFieldCondition:
    def __init__(self, *, key: str, match: FakeMatchValue) -> None:
        self.key = key
        self.match = match


class FakeFilter:
    def __init__(self, *, must: list[FakeFieldCondition]) -> None:
        self.must = must


class FakeModels:
    PointStruct = FakePointStruct
    MatchValue = FakeMatchValue
    FieldCondition = FakeFieldCondition
    Filter = FakeFilter


class FakeQdrantClient:
    def __init__(self) -> None:
        self.available = True
        self.query_points_result: list[object] = []
        self.queries: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []

    def query_points(self, **kwargs: Any) -> object:
        if not self.available:
            raise ConnectionError("qdrant offline")
        self.queries.append(kwargs)
        return SimpleNamespace(points=self.query_points_result)

    def upsert(self, **kwargs: Any) -> None:
        if not self.available:
            raise ConnectionError("qdrant offline")
        self.upserts.append(kwargs)


def _qdrant(client: FakeQdrantClient) -> QdrantService:
    return QdrantService(
        collection_name="mine_trace_evidence",
        client=client,
        models_module=FakeModels,
    )


def _filter_values(filter_obj: object) -> dict[str, str]:
    must = getattr(filter_obj, "must", None) or []
    values: dict[str, str] = {}
    for condition in must:
        match = getattr(condition, "match", None)
        values[str(getattr(condition, "key"))] = str(getattr(match, "value"))
    return values


@pytest.fixture
def semantic_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'semantic.db'}",
        sqlite_wal_enabled=False,
        semantic_search_enabled=True,
        semantic_top_k=5,
        semantic_score_threshold=None,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_a = uuid4()
    machine_b = uuid4()
    component_a1 = uuid4()
    component_a2 = uuid4()
    component_b1 = uuid4()
    with factory.begin() as session:
        session.add_all([MachineRecord(id=machine_a), MachineRecord(id=machine_b)])
        session.flush()
        session.add_all(
            [
                ComponentRecord(id=component_a1, machine_id=machine_a),
                ComponentRecord(id=component_a2, machine_id=machine_a),
                ComponentRecord(id=component_b1, machine_id=machine_b),
            ]
        )

    try:
        yield {
            "settings": settings,
            "factory": factory,
            "machine_a": machine_a,
            "machine_b": machine_b,
            "component_a1": component_a1,
            "component_a2": component_a2,
            "component_b1": component_b1,
        }
    finally:
        engine.dispose()


def _add_evidence(
    env: dict[str, Any],
    *,
    machine_id: UUID,
    component_id: UUID | None,
    record_id: str,
    event_type: str = "HYDRAULIC_WARNING",
    payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_type: str = "HUMAN_OBSERVATION",
    occurred_at: datetime | None = None,
) -> UUID:
    evidence_id = uuid4()
    with env["factory"].begin() as session:
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                component_id=component_id,
                source_type=source_type,
                original_source_record_id=record_id,
                original_timestamp=occurred_at
                or datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
                canonical_event_type=event_type,
                canonical_payload=payload or {"note": f"hydraulic note {record_id}"},
                raw_source_payload={"record": record_id, "untrusted": "raw"},
                provenance=provenance or {"source_system": "canonical-test"},
            )
        )
    return evidence_id


def _service(
    env: dict[str, Any],
    embedding: FakeEmbeddingProvider,
    client: FakeQdrantClient,
    *,
    settings: Settings | None = None,
    observability: MLAIObservability | None = None,
) -> SemanticHistoryService:
    return SemanticHistoryService(
        lambda: SQLAlchemyUnitOfWork(env["factory"]),
        embedding,
        _qdrant(client),
        settings or env["settings"],
        observability=observability,
    )


def _point(evidence_id: UUID | None, score: float, **extra_payload: str) -> object:
    payload = dict(extra_payload)
    if evidence_id is not None:
        payload["evidence_id"] = str(evidence_id)
    return SimpleNamespace(payload=payload, score=score)


def test_semantic_retrieval_uses_query_embedding_qdrant_and_canonical_hydration(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=semantic_env["component_a1"],
        record_id="query",
        payload={"observation": "pump emits a sharp whining noise"},
    )
    historical_time = datetime(2026, 9, 20, 8, 30, tzinfo=timezone.utc)
    historical_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=semantic_env["component_a1"],
        record_id="history",
        payload={"technician_note": "high pitched whine near hydraulic pump"},
        provenance={"source_system": "canonical-maintenance-log", "record": "m-77"},
        source_type="MAINTENANCE_RECORD",
        occurred_at=historical_time,
    )
    embedding = FakeEmbeddingProvider(query_vector=(0.4, 0.8))
    client = FakeQdrantClient()
    # Qdrant payload deliberately contains no canonical content/provenance.
    client.query_points_result = [_point(historical_id, 0.91, machine_id="derived-only")]

    response = _service(semantic_env, embedding, client).search_similar_history(query_id)

    assert response.available is True
    assert response.failure is None
    assert len(response.results) == 1
    result = response.results[0]
    assert result.match_type == "SEMANTIC"
    assert result.evidence_id == historical_id
    assert result.machine_id == semantic_env["machine_a"]
    assert result.component_id == semantic_env["component_a1"]
    assert result.evidence_type == "MAINTENANCE_RECORD"
    assert result.canonical_payload == {
        "technician_note": "high pitched whine near hydraulic pump"
    }
    assert result.provenance == {
        "source_system": "canonical-maintenance-log",
        "record": "m-77",
    }
    assert result.original_timestamp == historical_time
    assert result.similarity_score == 0.91
    assert len(embedding.query_texts) == 1
    assert "pump emits a sharp whining noise" in embedding.query_texts[0]
    query_call = client.queries[0]
    assert query_call["query"] == [0.4, 0.8]
    assert query_call["limit"] == 5
    assert "score_threshold" not in query_call


def test_same_machine_filter_is_sent_to_qdrant_and_rechecked_canonically(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="machine-query",
    )
    wrong_machine_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_b"],
        component_id=None,
        record_id="wrong-machine",
    )
    client = FakeQdrantClient()
    # Simulate stale/malformed Qdrant metadata that somehow bypassed its filter.
    client.query_points_result = [_point(wrong_machine_id, 0.99)]

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client
    ).search_similar_history(query_id)

    assert response.available is True
    assert response.results == []
    assert _filter_values(client.queries[0]["query_filter"]) == {
        "machine_id": str(semantic_env["machine_a"])
    }


def test_same_component_filter_is_sent_to_qdrant_and_rechecked_canonically(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=semantic_env["component_a1"],
        record_id="component-query",
    )
    wrong_component_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=semantic_env["component_a2"],
        record_id="wrong-component",
    )
    client = FakeQdrantClient()
    client.query_points_result = [_point(wrong_component_id, 0.93)]

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client
    ).search_similar_history(query_id)

    assert response.results == []
    assert _filter_values(client.queries[0]["query_filter"]) == {
        "machine_id": str(semantic_env["machine_a"]),
        "component_id": str(semantic_env["component_a1"]),
    }


def test_stale_qdrant_id_is_discarded_after_mandatory_canonical_hydration(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="stale-query",
    )
    client = FakeQdrantClient()
    client.query_points_result = [_point(uuid4(), 0.97)]

    observability = MLAIObservability()
    response = _service(
        semantic_env, FakeEmbeddingProvider(), client, observability=observability
    ).search_similar_history(query_id)

    assert response.available is True
    assert response.results == []
    assert observability.snapshot().stale_qdrant_reference_count == 1


def test_qdrant_point_missing_evidence_id_is_rejected_before_hydration(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="missing-id-query",
    )
    client = FakeQdrantClient()
    client.query_points_result = [
        _point(None, 0.99, machine_id=str(semantic_env["machine_a"]))
    ]

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client
    ).search_similar_history(query_id)

    assert response.available is True
    assert response.results == []


def test_configured_top_k_is_passed_to_qdrant_and_caps_final_results(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="top-k-query",
    )
    candidate_ids = [
        _add_evidence(
            semantic_env,
            machine_id=semantic_env["machine_a"],
            component_id=None,
            record_id=f"candidate-{index}",
        )
        for index in range(4)
    ]
    settings = Settings(
        environment="test",
        database_url=semantic_env["settings"].database_url,
        sqlite_wal_enabled=False,
        semantic_search_enabled=True,
        semantic_top_k=2,
        semantic_score_threshold=None,
    )
    client = FakeQdrantClient()
    # A real Qdrant server honors limit=2. Returning extra points here also tests
    # that the service does not exceed configured top-K if a transport double does.
    client.query_points_result = [
        _point(evidence_id, 0.9 - index * 0.01)
        for index, evidence_id in enumerate(candidate_ids)
    ]

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client, settings=settings
    ).search_similar_history(query_id)

    assert client.queries[0]["limit"] == 2
    assert len(response.results) == 2


def test_optional_score_threshold_is_forwarded_without_local_probability_semantics(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="threshold-query",
    )
    settings = Settings(
        environment="test",
        database_url=semantic_env["settings"].database_url,
        sqlite_wal_enabled=False,
        semantic_search_enabled=True,
        semantic_top_k=5,
        semantic_score_threshold=0.42,
    )
    client = FakeQdrantClient()

    _service(
        semantic_env, FakeEmbeddingProvider(), client, settings=settings
    ).search_similar_history(query_id)

    assert client.queries[0]["score_threshold"] == 0.42


def test_qdrant_outage_returns_typed_unavailable_without_touching_canonical_data(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="offline-query",
    )
    client = FakeQdrantClient()
    client.available = False

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client
    ).search_similar_history(query_id)

    assert response.available is False
    assert response.failure is SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
    assert response.results == []
    with SQLAlchemyUnitOfWork(semantic_env["factory"]) as uow:
        assert uow.evidence_events.get(query_id) is not None


def test_semantic_search_disabled_does_not_embed_or_query_qdrant(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="disabled-query",
    )
    settings = Settings(
        environment="test",
        database_url=semantic_env["settings"].database_url,
        sqlite_wal_enabled=False,
        semantic_search_enabled=False,
    )
    embedding = FakeEmbeddingProvider()
    client = FakeQdrantClient()

    response = _service(
        semantic_env, embedding, client, settings=settings
    ).search_similar_history(query_id)

    assert response.available is False
    assert response.failure is SemanticHistoryFailure.SEMANTIC_SEARCH_DISABLED
    assert response.results == []
    assert embedding.query_texts == []
    assert client.queries == []


def test_empty_qdrant_result_is_honest_available_zero_match_response(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="empty-query",
    )
    client = FakeQdrantClient()
    client.query_points_result = []

    response = _service(
        semantic_env, FakeEmbeddingProvider(), client
    ).search_similar_history(query_id)

    assert response.available is True
    assert response.failure is None
    assert response.results == []


def test_embedding_failure_degrades_without_querying_qdrant(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="embedding-failure-query",
    )
    embedding = FakeEmbeddingProvider(query_error=RuntimeError("embedding unavailable"))
    client = FakeQdrantClient()

    response = _service(semantic_env, embedding, client).search_similar_history(query_id)

    assert response.available is False
    assert response.failure is SemanticHistoryFailure.EMBEDDING_UNAVAILABLE
    assert response.results == []
    assert client.queries == []


def test_ineligible_query_content_returns_honest_zero_matches_without_embedding(
    semantic_env: dict[str, Any],
) -> None:
    query_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=None,
        record_id="numeric-only-query",
        payload={"pressure": 12.4, "temperature": 87},
    )
    embedding = FakeEmbeddingProvider()
    client = FakeQdrantClient()

    response = _service(semantic_env, embedding, client).search_similar_history(query_id)

    assert response.available is True
    assert response.results == []
    assert embedding.query_texts == []
    assert client.queries == []


def test_legacy_best_effort_indexing_still_uses_canonical_document_only(
    semantic_env: dict[str, Any],
) -> None:
    evidence_id = _add_evidence(
        semantic_env,
        machine_id=semantic_env["machine_a"],
        component_id=semantic_env["component_a1"],
        record_id="index-me",
        payload={"note": "technician heard a repeating hydraulic whine"},
    )
    embedding = FakeEmbeddingProvider(document_vector=(0.2, 0.3, 0.4))
    client = FakeQdrantClient()

    indexed = _service(semantic_env, embedding, client).index_evidence(evidence_id)

    assert indexed is True
    assert len(client.upserts) == 1
    point = client.upserts[0]["points"][0]
    assert str(point.id) == str(evidence_id)
    assert point.payload == {
        "evidence_id": str(evidence_id),
        "machine_id": str(semantic_env["machine_a"]),
        "component_id": str(semantic_env["component_a1"]),
        "evidence_type": "HUMAN_OBSERVATION",
    }
    assert len(embedding.document_texts) == 1
    assert "technician heard a repeating hydraulic whine" in embedding.document_texts[0]
