from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.sync import parse_sync_envelope, with_computed_checksum
from app.db.base import Base
from app.domain.enums import SemanticIndexOutboxStatus
from app.integrations.embeddings import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantCollectionResult,
    QdrantDistance,
    QdrantMutationResult,
)
from app.models import EvidenceEventRecord, SemanticIndexOutboxRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.semantic_indexing import (
    CanonicalEvidenceIndexingService,
    DurableSemanticIndexingCoordinator,
)
from app.services.sync_ingestion import GlobalSyncIngestionService
from tests.sync_test_data import ZERO_CHECKSUM, envelope_payload, signed_envelope


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.fail = False

    def _vector(self, text: str, kind: EmbeddingKind) -> EmbeddingVector:
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return EmbeddingVector.validated(
            (float(len(text)), 1.0, 2.0),
            provider="test",
            model="test-model",
            kind=kind,
        )

    def embed_documents(self, texts):
        return tuple(self._vector(text, EmbeddingKind.DOCUMENT) for text in texts)

    def embed_document(self, text: str):
        return self._vector(text, EmbeddingKind.DOCUMENT)

    def embed_query(self, text: str):
        return self._vector(text, EmbeddingKind.QUERY)


class CapturingQdrant:
    def __init__(self) -> None:
        self.available = True
        self.points: dict[str, dict] = {}
        self.vector_size: int | None = None

    def initialize_collection(self, *, vector_size: int):
        if not self.available:
            return QdrantCollectionResult(
                availability=QdrantAvailability.UNAVAILABLE,
                collection_name="mine_trace_evidence",
                exists=False,
                compatible=None,
                expected_vector_size=vector_size,
                actual_vector_size=None,
                expected_distance=QdrantDistance.COSINE,
                actual_distance=None,
                reason="qdrant_unavailable",
            )
        self.vector_size = vector_size
        return QdrantCollectionResult(
            availability=QdrantAvailability.AVAILABLE,
            collection_name="mine_trace_evidence",
            exists=True,
            compatible=True,
            expected_vector_size=vector_size,
            actual_vector_size=vector_size,
            expected_distance=QdrantDistance.COSINE,
            actual_distance=QdrantDistance.COSINE,
            created=True,
        )

    def delete_collection(self):
        if not self.available:
            return QdrantMutationResult(
                availability=QdrantAvailability.UNAVAILABLE,
                succeeded=False,
                reason="qdrant_unavailable",
            )
        self.points.clear()
        self.vector_size = None
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True)

    def upsert_semantic_document(self, *, document, vector):
        point_id = str(document.evidence_id)
        if not self.available:
            return QdrantMutationResult(
                QdrantAvailability.UNAVAILABLE,
                False,
                point_id=point_id,
                reason="qdrant_unavailable",
            )
        self.points[point_id] = {
            "vector": tuple(vector),
            "evidence_id": document.evidence_id,
            "machine_id": document.machine_id,
            "component_id": document.component_id,
            "incident_id": document.incident_id,
            "session_id": document.session_id,
            "machine_type": document.machine_type,
            "model": document.model,
            "site": document.site,
        }
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True, point_id=point_id)

    def upsert_vector(self, **kwargs):
        raise AssertionError("enriched semantic-document path should be used")

    def delete_vector(self, *, evidence_id):
        self.points.pop(str(evidence_id), None)
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True, point_id=str(evidence_id))


@pytest.fixture
def semantic_runtime(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'semantic.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def uow_factory():
        return SQLAlchemyUnitOfWork(factory)

    embedding = FakeEmbeddingProvider()
    qdrant = CapturingQdrant()
    indexer = CanonicalEvidenceIndexingService(uow_factory, embedding, qdrant)  # type: ignore[arg-type]
    coordinator = DurableSemanticIndexingCoordinator(factory, indexer)
    yield factory, embedding, qdrant, coordinator
    engine.dispose()


def _outbox(factory, evidence_id: UUID):
    with factory() as session:
        return session.scalar(
            select(SemanticIndexOutboxRecord).where(
                SemanticIndexOutboxRecord.evidence_id == evidence_id
            )
        )


def test_indexing_becomes_processable_only_after_canonical_commit(semantic_runtime) -> None:
    factory, _embedding, qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id

    with factory() as session:
        result = GlobalSyncIngestionService(session).ingest(envelope)
        assert result.semantic_evidence_ids == (evidence_id,)

    assert qdrant.points == {}
    row = _outbox(factory, evidence_id)
    assert row is not None and row.status == SemanticIndexOutboxStatus.PENDING.value

    run = coordinator.process_evidence_ids((evidence_id,))
    assert run.indexed == 1
    assert str(evidence_id) in qdrant.points
    row = _outbox(factory, evidence_id)
    assert row is not None and row.status == SemanticIndexOutboxStatus.INDEXED.value


def test_rollback_creates_no_outbox_or_vector(semantic_runtime, monkeypatch) -> None:
    factory, _embedding, qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id

    with factory() as session:
        service = GlobalSyncIngestionService(session)
        monkeypatch.setattr(service, "_new_receipt", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("force rollback")))
        with pytest.raises(RuntimeError, match="force rollback"):
            service.ingest(envelope)

    with factory() as session:
        assert session.get(EvidenceEventRecord, evidence_id) is None
        assert session.scalar(select(func.count()).select_from(SemanticIndexOutboxRecord)) == 0
    assert coordinator.process_evidence_ids((evidence_id,)).attempted == 0
    assert qdrant.points == {}


def test_qdrant_failure_is_retryable_and_canonical_evidence_remains(semantic_runtime) -> None:
    factory, _embedding, qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id
    with factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)

    qdrant.available = False
    run = coordinator.process_evidence_ids((evidence_id,))
    assert run.retryable_failed == 1
    with factory() as session:
        assert session.get(EvidenceEventRecord, evidence_id) is not None
    row = _outbox(factory, evidence_id)
    assert row is not None and row.status == SemanticIndexOutboxStatus.FAILED_RETRYABLE.value


def test_embedding_failure_is_retryable_and_canonical_evidence_remains(semantic_runtime) -> None:
    factory, embedding, _qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id
    with factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)

    embedding.fail = True
    run = coordinator.process_evidence_ids((evidence_id,))
    assert run.retryable_failed == 1
    with factory() as session:
        assert session.get(EvidenceEventRecord, evidence_id) is not None
    row = _outbox(factory, evidence_id)
    assert row is not None and row.status == SemanticIndexOutboxStatus.FAILED_RETRYABLE.value
    assert row.last_error and row.last_error.startswith("embedding_failed:")


def test_vector_payload_contains_canonical_filter_ids_and_machine_metadata(semantic_runtime) -> None:
    factory, _embedding, qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence = envelope.evidence_manifest.entries[0]
    incident = envelope.incident_updates[0]
    with factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)
    coordinator.process_evidence_ids((evidence.evidence_id,))

    payload = qdrant.points[str(evidence.evidence_id)]
    assert payload["evidence_id"] == evidence.evidence_id
    assert payload["machine_id"] == envelope.source_machine_id
    assert payload["component_id"] == evidence.component_id
    assert payload["incident_id"] == incident.incident_id
    assert payload["session_id"] == envelope.session_id
    assert payload["machine_type"] == "HAUL_TRUCK"
    assert payload["model"] == "MT-100"
    assert payload["site"] == "North Pit"


def test_rebuild_restores_deleted_qdrant_from_postgresql_outbox(semantic_runtime) -> None:
    factory, _embedding, qdrant, coordinator = semantic_runtime
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id
    with factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)
    coordinator.process_evidence_ids((evidence_id,))
    assert str(evidence_id) in qdrant.points

    qdrant.points.clear()  # simulate disposable collection loss
    assert qdrant.points == {}
    rebuilt = coordinator.rebuild_from_postgresql()
    assert rebuilt.indexed == 1
    assert str(evidence_id) in qdrant.points
    with factory() as session:
        assert session.get(EvidenceEventRecord, evidence_id) is not None


def test_numeric_only_canonical_evidence_is_skipped_deterministically(semantic_runtime) -> None:
    factory, embedding, qdrant, coordinator = semantic_runtime
    payload = envelope_payload()
    evidence_id = UUID(payload["evidence_manifest"]["entries"][0]["evidence_id"])
    payload["evidence_manifest"]["entries"][0]["canonical_payload"] = {
        "temperature": 91.2,
        "rpm": 1800,
        "alarm": False,
    }
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    envelope = with_computed_checksum(parse_sync_envelope(payload))
    with factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)

    first = coordinator.process_evidence_ids((evidence_id,))
    assert first.skipped == 1
    assert embedding.fail is False
    assert qdrant.points == {}
    row = _outbox(factory, evidence_id)
    assert row is not None and row.status == SemanticIndexOutboxStatus.SKIPPED_INELIGIBLE.value
    second = coordinator.process_evidence_ids((evidence_id,))
    assert second.attempted == 0
