"""Real Qdrant + PostgreSQL integration tests for the MINE-TRACE semantic pipeline.

These tests are intentionally opt-in. They require actual external services and never
fall back to an in-memory vector implementation.

Required environment:

    MINE_TRACE_RUN_REAL_QDRANT_INTEGRATION=1
    MINE_TRACE_TEST_QDRANT_URL=http://127.0.0.1:6333
    MINE_TRACE_TEST_POSTGRES_URL=postgresql+psycopg://mine_trace:mine_trace@127.0.0.1:55432/mine_trace_test

Optional:

    MINE_TRACE_TEST_QDRANT_API_KEY=...

Every run uses a random ``mine_trace_it_*`` Qdrant collection and PostgreSQL schema.
Only those generated resources are ever deleted by this suite.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import get_db_session
from app.domain.enums import IncidentStatus
from app.integrations.embeddings import EmbeddingKind, EmbeddingProvider, EmbeddingVector
from app.integrations.qdrant import QdrantAvailability, QdrantDistance, QdrantService
from app.main import app
from app.models import ComponentRecord, EvidenceEventRecord, IncidentRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_history import SemanticHistoryFailure
from app.services.semantic_history import SemanticHistoryService
from app.services.semantic_indexing import (
    CanonicalEvidenceIndexingService,
    SemanticIndexingState,
    SemanticRebuildState,
)

pytestmark = pytest.mark.real_qdrant

_ITEST_PREFIX = "mine_trace_it_"
_VECTOR_SIZE = 12


def _real_services_enabled() -> bool:
    return os.getenv("MINE_TRACE_RUN_REAL_QDRANT_INTEGRATION") == "1"


def _postgres_driver_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _safe_generated_name(value: str) -> str:
    if not value.startswith(_ITEST_PREFIX):
        raise RuntimeError(f"refusing destructive integration-test operation for {value!r}")
    return value


class DeterministicIntegrationEmbeddingProvider(EmbeddingProvider):
    """Deterministic test embedding provider; Qdrant itself remains real.

    The suite is testing the real vector database/index/search/hydration pipeline,
    not the availability or quality of a third-party embedding endpoint. Keeping
    embedding deterministic makes ranking assertions repeatable and removes an
    unrelated external service from this integration boundary.
    """

    provider = "integration-deterministic"
    model = "mine-trace-real-qdrant-test-v1"
    _keywords = (
        "brake",
        "grinding",
        "hydraulic",
        "pressure",
        "temperature",
        "leak",
        "engine",
        "vibration",
        "pump",
        "bearing",
        "noise",
    )

    @classmethod
    def _values(cls, text_value: str) -> tuple[float, ...]:
        text_lower = text_value.lower()
        values = [float(text_lower.count(keyword)) for keyword in cls._keywords]
        # Stable final dimension avoids a zero vector and adds mild lexical spread.
        digest = hashlib.sha256(text_value.encode("utf-8")).digest()
        values.append(0.1 + digest[0] / 2550.0)
        return tuple(values)

    def embed_document(self, text_value: str) -> EmbeddingVector:
        return EmbeddingVector.validated(
            self._values(text_value),
            provider=self.provider,
            model=self.model,
            kind=EmbeddingKind.DOCUMENT,
        )

    def embed_query(self, text_value: str) -> EmbeddingVector:
        return EmbeddingVector.validated(
            self._values(text_value),
            provider=self.provider,
            model=self.model,
            kind=EmbeddingKind.QUERY,
        )

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        return tuple(self.embed_document(value) for value in texts)


@dataclass(slots=True)
class RealStack:
    qdrant_client: Any
    qdrant: QdrantService
    postgres_engine: Engine
    session_factory: sessionmaker[Session]
    uow_factory: Any
    embedding: DeterministicIntegrationEmbeddingProvider
    settings: Settings
    collection_name: str
    schema_name: str

    def indexing(self, *, batch_size: int = 64) -> CanonicalEvidenceIndexingService:
        return CanonicalEvidenceIndexingService(
            self.uow_factory,
            self.embedding,
            self.qdrant,
            batch_size=batch_size,
        )

    def semantic(self) -> SemanticHistoryService:
        return SemanticHistoryService(
            self.uow_factory,
            self.embedding,
            self.qdrant,
            self.settings,
        )


@pytest.fixture(scope="module")
def real_stack() -> Generator[RealStack, None, None]:
    if not _real_services_enabled():
        pytest.skip("set MINE_TRACE_RUN_REAL_QDRANT_INTEGRATION=1 to run real Qdrant tests")

    qdrant_url = os.getenv("MINE_TRACE_TEST_QDRANT_URL")
    postgres_url = os.getenv("MINE_TRACE_TEST_POSTGRES_URL")
    if not qdrant_url or not postgres_url:
        pytest.skip("real integration requires MINE_TRACE_TEST_QDRANT_URL and MINE_TRACE_TEST_POSTGRES_URL")

    qdrant_client_mod = pytest.importorskip("qdrant_client")
    pytest.importorskip("psycopg")

    token = uuid4().hex[:16]
    collection_name = _safe_generated_name(f"{_ITEST_PREFIX}{token}")
    schema_name = _safe_generated_name(f"{_ITEST_PREFIX}{token}")

    qdrant_client = qdrant_client_mod.QdrantClient(
        url=qdrant_url,
        api_key=os.getenv("MINE_TRACE_TEST_QDRANT_API_KEY") or None,
        timeout=5.0,
    )
    qdrant = QdrantService(
        collection_name=collection_name,
        distance=QdrantDistance.COSINE,
        client=qdrant_client,
    )

    # Prove this is an actual reachable Qdrant before any destructive operation.
    connectivity = qdrant.connectivity()
    if connectivity.availability is not QdrantAvailability.AVAILABLE:
        pytest.skip(f"test Qdrant unavailable: {connectivity.reason}")

    pg_url = _postgres_driver_url(postgres_url)
    admin_engine = create_engine(pg_url, pool_pre_ping=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    except Exception as exc:
        admin_engine.dispose()
        pytest.skip(f"test PostgreSQL unavailable or schema creation denied: {type(exc).__name__}")

    postgres_engine = create_engine(
        pg_url,
        connect_args={"options": f"-csearch_path={schema_name}"},
        pool_pre_ping=True,
    )
    # Only the canonical tables needed by this test suite are created in the
    # isolated schema. No production schema/table is dropped or truncated.
    Base.metadata.create_all(
        postgres_engine,
        tables=[
            MachineRecord.__table__,
            ComponentRecord.__table__,
            EvidenceEventRecord.__table__,
            IncidentRecord.__table__,
        ],
    )
    SessionFactory = sessionmaker(
        bind=postgres_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    uow_factory = lambda: SQLAlchemyUnitOfWork(SessionFactory)

    settings = Settings(
        environment="test",
        database_url=pg_url,
        semantic_search_enabled=True,
        qdrant_url=qdrant_url,
        qdrant_collection=collection_name,
        qdrant_distance="cosine",
        embedding_provider="integration-deterministic",
        embedding_model=DeterministicIntegrationEmbeddingProvider.model,
        semantic_top_k=5,
        semantic_score_threshold=None,
    )
    stack = RealStack(
        qdrant_client=qdrant_client,
        qdrant=qdrant,
        postgres_engine=postgres_engine,
        session_factory=SessionFactory,
        uow_factory=uow_factory,
        embedding=DeterministicIntegrationEmbeddingProvider(),
        settings=settings,
        collection_name=collection_name,
        schema_name=schema_name,
    )

    try:
        yield stack
    finally:
        # Destructive cleanup is guarded to the generated integration collection/schema.
        _safe_generated_name(collection_name)
        _safe_generated_name(schema_name)
        try:
            if qdrant_client.collection_exists(collection_name=collection_name):
                qdrant_client.delete_collection(collection_name=collection_name)
        finally:
            postgres_engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            admin_engine.dispose()
            close = getattr(qdrant_client, "close", None)
            if callable(close):
                close()


@pytest.fixture(autouse=True)
def clean_isolated_state(real_stack: RealStack) -> Generator[None, None, None]:
    _safe_generated_name(real_stack.collection_name)
    if real_stack.qdrant_client.collection_exists(collection_name=real_stack.collection_name):
        real_stack.qdrant_client.delete_collection(collection_name=real_stack.collection_name)

    with real_stack.session_factory() as session:
        session.execute(delete(EvidenceEventRecord))
        session.execute(delete(IncidentRecord))
        session.execute(delete(ComponentRecord))
        session.execute(delete(MachineRecord))
        session.commit()
    yield


def _machine(stack: RealStack, *, label: str = "EX-01") -> MachineRecord:
    row = MachineRecord(id=uuid4(), display_name=label, asset_code=f"asset-{uuid4().hex[:8]}")
    with stack.session_factory() as session:
        session.add(row)
        session.commit()
    return row


def _component(stack: RealStack, machine_id: UUID, *, label: str = "Brake") -> ComponentRecord:
    row = ComponentRecord(id=uuid4(), machine_id=machine_id, display_name=label)
    with stack.session_factory() as session:
        session.add(row)
        session.commit()
    return row


def _evidence(
    stack: RealStack,
    machine_id: UUID,
    *,
    text_value: str,
    component_id: UUID | None = None,
    source_type: str = "HUMAN_OBSERVATION",
    event_type: str = "OBSERVATION",
    seconds: int = 0,
) -> EvidenceEventRecord:
    evidence_id = uuid4()
    row = EvidenceEventRecord(
        id=evidence_id,
        machine_id=machine_id,
        component_id=component_id,
        source_type=source_type,
        original_source_record_id=f"real-it-{evidence_id}",
        original_timestamp=datetime(2026, 10, 3, 4, 0, tzinfo=UTC) + timedelta(seconds=seconds),
        canonical_event_type=event_type,
        canonical_payload={"note": text_value},
        raw_source_payload={"raw": "test-only"},
        provenance={"source": "real-qdrant-integration-test", "record": str(evidence_id)},
    )
    with stack.session_factory() as session:
        session.add(row)
        session.commit()
    return row


def _incident(stack: RealStack, machine_id: UUID) -> IncidentRecord:
    row = IncidentRecord(id=uuid4(), machine_id=machine_id, status=IncidentStatus.OPEN)
    with stack.session_factory() as session:
        session.add(row)
        session.commit()
    return row


def _count_points(stack: RealStack) -> int:
    result = stack.qdrant_client.count(collection_name=stack.collection_name, exact=True)
    return int(result.count)


def _retrieve_point(stack: RealStack, evidence_id: UUID):
    points = stack.qdrant_client.retrieve(
        collection_name=stack.collection_name,
        ids=[str(evidence_id)],
        with_payload=True,
        with_vectors=True,
    )
    return points[0] if points else None


def _initialize(stack: RealStack) -> None:
    result = stack.qdrant.initialize_collection(vector_size=_VECTOR_SIZE)
    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.compatible is True


def _unavailable_qdrant() -> QdrantService:
    qdrant_client_mod = pytest.importorskip("qdrant_client")
    client = qdrant_client_mod.QdrantClient(url="http://127.0.0.1:1", timeout=0.2)
    return QdrantService(
        collection_name=f"{_ITEST_PREFIX}unreachable",
        distance=QdrantDistance.COSINE,
        client=client,
    )


# 1

def test_real_qdrant_connectivity(real_stack: RealStack) -> None:
    result = real_stack.qdrant.connectivity()
    assert result.availability is QdrantAvailability.AVAILABLE


# 2

def test_real_collection_creation(real_stack: RealStack) -> None:
    result = real_stack.qdrant.initialize_collection(vector_size=_VECTOR_SIZE)
    assert result.availability is QdrantAvailability.AVAILABLE
    assert result.created is True
    assert result.compatible is True
    assert real_stack.qdrant_client.collection_exists(collection_name=real_stack.collection_name)


# 3

def test_real_collection_compatibility_validation(real_stack: RealStack) -> None:
    _initialize(real_stack)
    compatible = real_stack.qdrant.validate_collection(vector_size=_VECTOR_SIZE)
    incompatible = real_stack.qdrant.validate_collection(vector_size=_VECTOR_SIZE + 1)
    assert compatible.compatible is True
    assert incompatible.compatible is False
    assert incompatible.reason and "vector_size_mismatch" in incompatible.reason


# 4

def test_real_vector_insertion(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="brake grinding noise")
    result = real_stack.indexing().index_evidence(evidence.id)
    assert result.state is SemanticIndexingState.INDEXED
    assert _count_points(real_stack) == 1


# 5

def test_real_qdrant_payload_contains_canonical_evidence_id(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="hydraulic pressure leak")
    assert real_stack.indexing().index_evidence(evidence.id).indexed
    point = _retrieve_point(real_stack, evidence.id)
    assert point is not None
    assert point.payload["evidence_id"] == str(evidence.id)
    assert point.payload["machine_id"] == str(machine.id)


# 6

def test_real_upsert_is_deterministic_and_idempotent(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="brake grinding vibration")
    first = real_stack.indexing().index_evidence(evidence.id)
    second = real_stack.indexing().index_evidence(evidence.id)
    assert first.point_id == second.point_id == str(evidence.id)
    assert _count_points(real_stack) == 1


# 7

def test_real_batch_indexing(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = [
        _evidence(real_stack, machine.id, text_value=value, seconds=index)
        for index, value in enumerate(("brake noise", "hydraulic pressure", "bearing vibration"))
    ]
    result = real_stack.indexing(batch_size=2).batch_index(tuple(row.id for row in evidence))
    assert result.indexed == 3
    assert result.failed == 0
    assert result.unavailable == 0
    assert _count_points(real_stack) == 3


# 8

def test_real_reindex_replaces_vector_from_updated_canonical_text(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="brake grinding noise")
    service = real_stack.indexing()
    assert service.index_evidence(evidence.id).indexed
    before = tuple(_retrieve_point(real_stack, evidence.id).vector)

    with real_stack.session_factory() as session:
        canonical = session.get(EvidenceEventRecord, evidence.id)
        assert canonical is not None
        canonical.canonical_payload = {"note": "hydraulic pressure leak pump"}
        session.commit()

    assert service.reindex_evidence(evidence.id).indexed
    after = tuple(_retrieve_point(real_stack, evidence.id).vector)
    assert before != after
    assert _count_points(real_stack) == 1


# 9

def test_real_machine_filter(real_stack: RealStack) -> None:
    machine_a = _machine(real_stack, label="EX-A")
    machine_b = _machine(real_stack, label="EX-B")
    a = _evidence(real_stack, machine_a.id, text_value="brake grinding noise")
    b = _evidence(real_stack, machine_b.id, text_value="brake grinding noise")
    assert real_stack.indexing().batch_index((a.id, b.id)).indexed == 2
    query = real_stack.embedding.embed_query("brake grinding noise")
    result = real_stack.qdrant.vector_search(vector=query.values, machine_id=machine_a.id, top_k=10)
    assert result.availability is QdrantAvailability.AVAILABLE
    assert {hit.evidence_id for hit in result.hits} == {a.id}


# 10

def test_real_component_filter(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    component_a = _component(real_stack, machine.id, label="Brake A")
    component_b = _component(real_stack, machine.id, label="Brake B")
    a = _evidence(real_stack, machine.id, component_id=component_a.id, text_value="brake grinding noise")
    b = _evidence(real_stack, machine.id, component_id=component_b.id, text_value="brake grinding noise")
    assert real_stack.indexing().batch_index((a.id, b.id)).indexed == 2
    query = real_stack.embedding.embed_query("brake grinding noise")
    result = real_stack.qdrant.vector_search(
        vector=query.values,
        machine_id=machine.id,
        component_id=component_a.id,
        top_k=10,
    )
    assert {hit.evidence_id for hit in result.hits} == {a.id}


# 11

def test_real_top_k_search(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    rows = [
        _evidence(real_stack, machine.id, text_value=f"brake grinding noise {index}", seconds=index)
        for index in range(5)
    ]
    assert real_stack.indexing().batch_index(tuple(row.id for row in rows)).indexed == 5
    query = real_stack.embedding.embed_query("brake grinding noise")
    result = real_stack.qdrant.vector_search(vector=query.values, machine_id=machine.id, top_k=2)
    assert len(result.hits) == 2


# 12

def test_real_candidate_hydrates_through_postgresql(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    component = _component(real_stack, machine.id)
    query = _evidence(real_stack, machine.id, component_id=component.id, text_value="brake grinding noise", seconds=1)
    candidate = _evidence(real_stack, machine.id, component_id=component.id, text_value="brake grinding reported previously", seconds=2)
    assert real_stack.indexing().batch_index((query.id, candidate.id)).indexed == 2

    result = real_stack.semantic().search_similar_history(query.id)
    hydrated = next(item for item in result.results if item.evidence_id == candidate.id)
    assert hydrated.canonical_payload == candidate.canonical_payload
    assert hydrated.provenance == candidate.provenance
    assert hydrated.machine_id == machine.id
    assert hydrated.component_id == component.id


# 13

def test_real_stale_qdrant_id_is_discarded(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    query = _evidence(real_stack, machine.id, text_value="brake grinding noise")
    assert real_stack.indexing().index_evidence(query.id).indexed
    stale_id = uuid4()
    vector = real_stack.embedding.embed_document("brake grinding noise")
    assert real_stack.qdrant.upsert_vector(
        evidence_id=stale_id,
        machine_id=machine.id,
        component_id=None,
        evidence_type="HUMAN_OBSERVATION",
        vector=vector.values,
    ).succeeded

    result = real_stack.semantic().search_similar_history(query.id)
    assert all(item.evidence_id != stale_id for item in result.results)


# 14

def test_real_deleted_canonical_evidence_is_not_returned_from_stale_vector(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    query = _evidence(real_stack, machine.id, text_value="hydraulic pressure leak", seconds=1)
    candidate = _evidence(real_stack, machine.id, text_value="hydraulic pressure leak observed", seconds=2)
    assert real_stack.indexing().batch_index((query.id, candidate.id)).indexed == 2

    with real_stack.session_factory() as session:
        session.execute(delete(EvidenceEventRecord).where(EvidenceEventRecord.id == candidate.id))
        session.commit()
    assert _retrieve_point(real_stack, candidate.id) is not None

    result = real_stack.semantic().search_similar_history(query.id)
    assert all(item.evidence_id != candidate.id for item in result.results)


# 15

def test_real_vector_deletion_preserves_canonical_evidence(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="bearing vibration noise")
    service = real_stack.indexing()
    assert service.index_evidence(evidence.id).indexed
    removed = service.remove_derived_vector(evidence.id)
    assert removed.state is SemanticIndexingState.REMOVED
    assert _retrieve_point(real_stack, evidence.id) is None
    with real_stack.uow_factory() as uow:
        assert uow.evidence_events.get(evidence.id) is not None


# 16

def test_real_empty_qdrant_collection_does_not_damage_backend(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="engine temperature observation")
    _initialize(real_stack)
    result = real_stack.semantic().search_similar_history(evidence.id)
    assert result.available is True
    assert result.results == []
    with real_stack.uow_factory() as uow:
        assert uow.evidence_events.get(evidence.id) is not None


# 17

def test_real_entire_qdrant_collection_can_be_rebuilt(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    rows = [
        _evidence(real_stack, machine.id, text_value=value, seconds=index)
        for index, value in enumerate(("brake noise", "hydraulic leak", "bearing vibration"))
    ]
    _initialize(real_stack)
    stale_id = uuid4()
    vector = real_stack.embedding.embed_document("stale brake noise")
    assert real_stack.qdrant.upsert_vector(
        evidence_id=stale_id,
        machine_id=machine.id,
        component_id=None,
        evidence_type="HUMAN_OBSERVATION",
        vector=vector.values,
    ).succeeded

    rebuilt = real_stack.indexing(batch_size=2).rebuild_qdrant_index()
    assert rebuilt.state is SemanticRebuildState.REBUILT
    assert rebuilt.indexed == 3
    assert _count_points(real_stack) == 3
    assert _retrieve_point(real_stack, stale_id) is None
    assert all(_retrieve_point(real_stack, row.id) is not None for row in rows)


# 18

def test_real_qdrant_unavailable_returns_degraded_semantic_state(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    evidence = _evidence(real_stack, machine.id, text_value="brake grinding noise")
    service = SemanticHistoryService(
        real_stack.uow_factory,
        real_stack.embedding,
        _unavailable_qdrant(),
        real_stack.settings,
    )
    result = service.search_similar_history(evidence.id)
    assert result.available is False
    assert result.failure is SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
    assert result.results == []


# 19

def test_canonical_fastapi_reads_remain_operational_during_qdrant_outage(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    _incident(real_stack, machine.id)
    assert _unavailable_qdrant().connectivity().availability is QdrantAvailability.UNAVAILABLE

    def override_get_db_session() -> Generator[Session, None, None]:
        session = real_stack.session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            machines = client.get("/api/v1/machines")
            incidents = client.get("/api/v1/incidents")
            assert machines.status_code == 200
            assert incidents.status_code == 200
            assert machines.json()["total"] == 1
            assert incidents.json()["total"] == 1
    finally:
        app.dependency_overrides.clear()


# 20

def test_real_semantic_match_is_labelled_semantic(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    query = _evidence(real_stack, machine.id, text_value="brake grinding noise", seconds=1)
    candidate = _evidence(real_stack, machine.id, text_value="previous brake grinding noise", seconds=2)
    assert real_stack.indexing().batch_index((query.id, candidate.id)).indexed == 2
    result = real_stack.semantic().search_similar_history(query.id)
    match = next(item for item in result.results if item.evidence_id == candidate.id)
    assert match.match_type == "SEMANTIC"


# 21

def test_real_similarity_score_is_not_exposed_as_factual_confidence(real_stack: RealStack) -> None:
    machine = _machine(real_stack)
    query = _evidence(real_stack, machine.id, text_value="brake grinding noise", seconds=1)
    candidate = _evidence(real_stack, machine.id, text_value="brake grinding noise history", seconds=2)
    assert real_stack.indexing().batch_index((query.id, candidate.id)).indexed == 2
    result = real_stack.semantic().search_similar_history(query.id)
    match = next(item for item in result.results if item.evidence_id == candidate.id)
    payload = match.model_dump(mode="json")
    assert isinstance(payload["similarity_score"], float)
    assert "confidence" not in payload
    assert "probability" not in payload
    schema = match.__class__.model_json_schema()
    description = schema["properties"]["similarity_score"]["description"].lower()
    assert "not confidence" in description
    assert "probability" in description
