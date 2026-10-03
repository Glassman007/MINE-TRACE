from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.domain.enums import IncidentEvidenceRelationshipType, IncidentStatus
from app.integrations.embeddings.base import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant.types import QdrantAvailability, QdrantSearchResult
from app.integrations.semantic import SemanticIndexHit
from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord, IncidentRecord, MachineRecord
from app.schemas.semantic_search import FleetSemanticSearchRequest, SemanticSearchState
from app.services.fleet_semantic_search import FleetSemanticSearchService

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class FakeEmbedding:
    def __init__(self, fail: bool = False): self.fail = fail
    def embed_query(self, text: str):
        if self.fail: raise RuntimeError("embedding down")
        return EmbeddingVector.validated([0.1, 0.2, 0.3], provider="fake", model="fake", kind=EmbeddingKind.QUERY)


class FakeQdrant:
    def __init__(self, hits=(), available=True):
        self.hits = tuple(hits); self.available = available; self.calls = []
    def vector_search(self, **kwargs):
        self.calls.append(kwargs)
        if not self.available:
            return QdrantSearchResult(QdrantAvailability.UNAVAILABLE, reason="down")
        return QdrantSearchResult(QdrantAvailability.AVAILABLE, hits=self.hits)


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'semantic-search.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    machine_a, machine_b = uuid4(), uuid4()
    evidence_a, evidence_b = uuid4(), uuid4()
    incident_a = uuid4()
    with factory() as s:
        s.add_all([
            MachineRecord(id=machine_a, display_name="A", machine_type="HAUL_TRUCK", model="MT-100", site_name="North"),
            MachineRecord(id=machine_b, display_name="B", machine_type="EXCAVATOR", model="EX-9", site_name="South"),
        ]); s.flush()
        s.add(IncidentRecord(id=incident_a, machine_id=machine_a, status=IncidentStatus.OPEN, first_seen_at=NOW-timedelta(hours=3)))
        s.add_all([
            EvidenceEventRecord(id=evidence_a, machine_id=machine_a, source_machine_id=machine_a, source_type="HUMAN_OBSERVATION", original_source_record_id="a", original_timestamp=NOW-timedelta(hours=2), canonical_event_type="NOTE", canonical_payload={"text":"hydraulic pump whine"}, raw_source_payload={}, provenance={"edge":"a"}),
            EvidenceEventRecord(id=evidence_b, machine_id=machine_b, source_machine_id=machine_b, source_type="HUMAN_OBSERVATION", original_source_record_id="b", original_timestamp=NOW-timedelta(hours=1), canonical_event_type="NOTE", canonical_payload={"text":"brake vibration"}, raw_source_payload={}, provenance={"edge":"b"}),
        ]); s.flush()
        s.add(IncidentEvidenceLinkRecord(id=uuid4(), incident_id=incident_a, evidence_event_id=evidence_a, is_active=True, relationship_type=IncidentEvidenceRelationshipType.RELATED, link_reason="edge supplied"))
        s.commit()
    yield factory, {"machine_a":machine_a,"machine_b":machine_b,"evidence_a":evidence_a,"evidence_b":evidence_b,"incident_a":incident_a}
    engine.dispose()


def _settings():
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db", semantic_search_enabled=True, qdrant_url="http://localhost:6333")


def test_cross_machine_retrieval_and_postgres_hydration(env):
    factory, ids = env
    q = FakeQdrant([SemanticIndexHit(ids["evidence_b"], .91), SemanticIndexHit(ids["evidence_a"], .87)])
    with factory() as s:
        response = FleetSemanticSearchService(s, FakeEmbedding(), q, _settings()).search(FleetSemanticSearchRequest(query="noise", top_k=10))
    assert response.state is SemanticSearchState.AVAILABLE
    assert [r.evidence_id for r in response.results] == [ids["evidence_b"], ids["evidence_a"]]
    assert response.results[0].canonical_payload == {"text":"brake vibration"}
    assert response.results[1].incident_ids == [ids["incident_a"]]
    assert all(r.match_type.value == "SEMANTIC_SIMILARITY" for r in response.results)


def test_filters_are_forwarded_and_rechecked_canonically(env):
    factory, ids = env
    q = FakeQdrant([SemanticIndexHit(ids["evidence_b"], .99), SemanticIndexHit(ids["evidence_a"], .8)])
    with factory() as s:
        response = FleetSemanticSearchService(s, FakeEmbedding(), q, _settings()).search(FleetSemanticSearchRequest(query="pump", machine_id=ids["machine_a"], machine_type="HAUL_TRUCK", model="MT-100", site="North", start=NOW-timedelta(hours=3), end=NOW, top_k=5))
    assert [r.evidence_id for r in response.results] == [ids["evidence_a"]]
    call = q.calls[0]
    assert call["machine_id"] == ids["machine_a"] and call["model"] == "MT-100" and call["site"] == "North"


def test_stale_qdrant_id_is_discarded(env):
    factory, ids = env
    q = FakeQdrant([SemanticIndexHit(uuid4(), .99), SemanticIndexHit(ids["evidence_a"], .7)])
    with factory() as s:
        response = FleetSemanticSearchService(s, FakeEmbedding(), q, _settings()).search(FleetSemanticSearchRequest(query="pump"))
    assert [r.evidence_id for r in response.results] == [ids["evidence_a"]]


def test_embedding_and_qdrant_failure_return_typed_degraded(env):
    factory, _ = env
    with factory() as s:
        a = FleetSemanticSearchService(s, FakeEmbedding(fail=True), FakeQdrant(), _settings()).search(FleetSemanticSearchRequest(query="x"))
        b = FleetSemanticSearchService(s, FakeEmbedding(), FakeQdrant(available=False), _settings()).search(FleetSemanticSearchRequest(query="x"))
    assert (a.state, a.reason) == (SemanticSearchState.DEGRADED, "embedding_unavailable")
    assert (b.state, b.reason) == (SemanticSearchState.DEGRADED, "semantic_index_unavailable")
