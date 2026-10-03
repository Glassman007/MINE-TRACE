from __future__ import annotations

import copy
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.sync import parse_sync_envelope, with_computed_checksum
from app.core.settings import Settings
from app.db.base import Base
from app.integrations.embeddings import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantCollectionResult,
    QdrantDistance,
    QdrantMutationResult,
    QdrantSearchResult,
)
from app.integrations.semantic import SemanticIndexHit
from app.models import EvidenceEventRecord, SessionReportRecord, SyncConflictRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_search import FleetSemanticSearchRequest, SemanticSearchState
from app.services.fleet_semantic_search import FleetSemanticSearchService
from app.services.semantic_indexing import CanonicalEvidenceIndexingService, DurableSemanticIndexingCoordinator
from app.services.sync_ingestion import GlobalSyncIngestionService
from tests.sync_test_data import ZERO_CHECKSUM, envelope_payload, signed_envelope


class LocalEmbeddingDouble:
    def _values(self, text: str):
        text = text.lower()
        if "hydraulic" in text or "pump" in text:
            return (1.0, 0.0, 0.0)
        if "brake" in text or "vibration" in text:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)

    def embed_documents(self, texts):
        return tuple(EmbeddingVector.validated(self._values(text), provider="local-test", model="bge-double", kind=EmbeddingKind.DOCUMENT) for text in texts)

    def embed_document(self, text: str):
        return EmbeddingVector.validated(self._values(text), provider="local-test", model="bge-double", kind=EmbeddingKind.DOCUMENT)

    def embed_query(self, text: str):
        return EmbeddingVector.validated(self._values(text), provider="local-test", model="bge-double", kind=EmbeddingKind.QUERY)


class DerivedQdrantDouble:
    def __init__(self):
        self.points: dict[UUID, dict] = {}
        self.available = True

    def initialize_collection(self, *, vector_size: int):
        return QdrantCollectionResult(QdrantAvailability.AVAILABLE, "mine_trace_evidence", True, True, vector_size, vector_size, QdrantDistance.COSINE, QdrantDistance.COSINE)

    def upsert_semantic_document(self, *, document, vector):
        self.points[document.evidence_id] = {"document": document, "vector": tuple(vector)}
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True, point_id=str(document.evidence_id))

    def delete_collection(self):
        self.points.clear()
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True)

    def delete_vector(self, *, evidence_id):
        self.points.pop(evidence_id, None)
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True, point_id=str(evidence_id))

    def vector_search(self, *, vector, machine_id=None, component_id=None, machine_type=None, model=None, site=None, start=None, end=None, top_k=10, score_threshold=None):
        if not self.available:
            return QdrantSearchResult(QdrantAvailability.UNAVAILABLE, reason="qdrant unavailable")
        hits = []
        for evidence_id, item in self.points.items():
            doc = item["document"]
            if machine_id is not None and doc.machine_id != machine_id: continue
            if component_id is not None and doc.component_id != component_id: continue
            if machine_type is not None and doc.machine_type != machine_type: continue
            if model is not None and doc.model != model: continue
            if site is not None and doc.site != site: continue
            score = sum(a * b for a, b in zip(vector, item["vector"], strict=True))
            if score_threshold is not None and score < score_threshold: continue
            hits.append(SemanticIndexHit(evidence_id=evidence_id, score=score))
        hits.sort(key=lambda item: item.score, reverse=True)
        return QdrantSearchResult(QdrantAvailability.AVAILABLE, hits=tuple(hits[:top_k]))


def _signed_custom(payload: dict):
    payload = copy.deepcopy(payload)
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    return with_computed_checksum(parse_sync_envelope(payload))


def test_multi_machine_sync_to_postcommit_index_to_canonical_hydrated_search(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'global-e2e.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    machine_a, machine_b = uuid4(), uuid4()
    session_a, session_b = uuid4(), uuid4()
    component_a, component_b = uuid4(), uuid4()
    incident_a, incident_b = uuid4(), uuid4()
    evidence_a, evidence_b = uuid4(), uuid4()
    action_a, action_b = uuid4(), uuid4()
    verification_a, verification_b = uuid4(), uuid4()
    report_a1, report_a2, report_b1 = uuid4(), uuid4(), uuid4()

    a1 = signed_envelope(machine_id=machine_a, session_id=session_a, component_id=component_a, incident_id=incident_a, evidence_id=evidence_a, action_id=action_a, verification_id=verification_a, report_id=report_a1, report_revision=1)
    b_payload = envelope_payload(machine_id=machine_b, session_id=session_b, component_id=component_b, incident_id=incident_b, evidence_id=evidence_b, action_id=action_b, verification_id=verification_b, report_id=report_b1, report_revision=1)
    b_payload["machine_session_report"]["machine"].update({"display_name": "Excavator B", "machine_type": "EXCAVATOR", "model": "EX-9", "site_name": "South Pit"})
    b_payload["evidence_manifest"]["entries"][0]["canonical_payload"] = {"text": "brake vibration reported"}
    b_payload["important_text_evidence"][0]["text"] = "brake vibration reported"
    b1 = _signed_custom(b_payload)

    with factory() as session:
        accepted_a = GlobalSyncIngestionService(session).ingest(a1)
        accepted_b = GlobalSyncIngestionService(session).ingest(b1)
    assert accepted_a.acknowledgement.status.value == "ACCEPTED"
    assert accepted_b.acknowledgement.status.value == "ACCEPTED"

    # Exact redelivery is idempotent.
    with factory() as session:
        duplicate = GlobalSyncIngestionService(session).ingest(a1)
    assert duplicate.acknowledgement == accepted_a.acknowledgement
    assert duplicate.acknowledgement.status.value == "ACCEPTED"

    # A newer report revision preserves revision 1 while stable evidence is deduplicated.
    a2 = signed_envelope(machine_id=machine_a, session_id=session_a, component_id=component_a, incident_id=incident_a, evidence_id=evidence_a, action_id=action_a, verification_id=verification_a, report_id=report_a2, report_revision=2)
    with factory() as session:
        newer = GlobalSyncIngestionService(session).ingest(a2)
        reports = session.scalars(select(SessionReportRecord).where(SessionReportRecord.session_id == session_a).order_by(SessionReportRecord.report_revision)).all()
        evidence_rows = session.scalars(select(EvidenceEventRecord).where(EvidenceEventRecord.id == evidence_a)).all()
    assert newer.acknowledgement.status.value == "ACCEPTED"
    assert [row.report_revision for row in reports] == [1, 2]
    assert len(evidence_rows) == 1

    # Same logical revision with incompatible content becomes an explicit conflict.
    conflict_payload = copy.deepcopy(b_payload)
    conflict_payload["package_id"] = str(uuid4())
    conflict_payload["machine_session_report"]["machine"]["display_name"] = "Conflicting B identity"
    conflict = _signed_custom(conflict_payload)
    with factory() as session:
        conflict_result = GlobalSyncIngestionService(session).ingest(conflict)
        conflict_rows = session.scalars(select(SyncConflictRecord).where(SyncConflictRecord.source_machine_id == machine_b)).all()
    assert conflict_result.acknowledgement.status.value == "CONFLICT"
    assert len(conflict_rows) == 1

    # Canonical rows exist before any derived vector is written.
    embedding = LocalEmbeddingDouble()
    qdrant = DerivedQdrantDouble()
    uow_factory = lambda: SQLAlchemyUnitOfWork(factory)
    indexer = CanonicalEvidenceIndexingService(uow_factory, embedding, qdrant)
    coordinator = DurableSemanticIndexingCoordinator(factory, indexer)
    assert qdrant.points == {}
    indexed = coordinator.process_evidence_ids((evidence_a, evidence_b))
    assert indexed.indexed == 2

    # Qdrant ranks candidates, but returned facts/provenance are hydrated from canonical SQL.
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", semantic_search_enabled=True, qdrant_url="http://qdrant.test")
    with factory() as session:
        search = FleetSemanticSearchService(session, embedding, qdrant, settings).search(FleetSemanticSearchRequest(query="hydraulic pump", top_k=5))
    assert search.state is SemanticSearchState.AVAILABLE
    assert search.results[0].evidence_id == evidence_a
    assert search.results[0].canonical_payload == {"text": "hydraulic whine observed"}
    assert search.results[0].provenance == {"edge": "operator-console"}
    assert search.results[0].incident_ids == [incident_a]

    # A stale vector reference is ignored rather than fabricated into a canonical result.
    stale_id = uuid4()
    qdrant.points[stale_id] = {"document": qdrant.points[evidence_a]["document"], "vector": (1.0, 0.0, 0.0)}
    # Re-keying simulates an obsolete point whose evidence_id no longer exists canonically.
    class StaleFirstQdrant(DerivedQdrantDouble):
        pass
    original_search = qdrant.vector_search
    def stale_first(**kwargs):
        result = original_search(**kwargs)
        return QdrantSearchResult(QdrantAvailability.AVAILABLE, hits=(SemanticIndexHit(stale_id, 1.1), *result.hits))
    qdrant.vector_search = stale_first
    with factory() as session:
        hydrated = FleetSemanticSearchService(session, embedding, qdrant, settings).search(FleetSemanticSearchRequest(query="hydraulic pump", top_k=5))
    assert all(item.evidence_id != stale_id for item in hydrated.results)

    engine.dispose()
