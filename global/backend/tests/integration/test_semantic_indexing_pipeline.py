from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.integrations.embeddings import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantCollectionResult,
    QdrantDistance,
    QdrantMutationResult,
    QdrantService,
)
from app.models import EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.semantic_indexing import (
    CanonicalEvidenceIndexingService,
    SemanticIndexingState,
    SemanticRebuildState,
)


class DeterministicEmbeddingProvider:
    def __init__(self) -> None:
        self.fail = False
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _vector(text: str) -> EmbeddingVector:
        values = (
            float(len(text)),
            float(sum(ord(char) for char in text) % 1009),
            float(text.count("\n") + 1),
        )
        return EmbeddingVector.validated(
            values,
            provider="test",
            model="deterministic",
            kind=EmbeddingKind.DOCUMENT,
        )

    def embed_document(self, text: str) -> EmbeddingVector:
        return self.embed_documents((text,))[0]

    def embed_query(self, text: str) -> EmbeddingVector:
        vector = self._vector(text)
        return EmbeddingVector.validated(
            vector.values,
            provider=vector.provider,
            model=vector.model,
            kind=EmbeddingKind.QUERY,
        )

    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("embedding offline")
        normalized = tuple(texts)
        self.calls.append(normalized)
        return tuple(self._vector(text) for text in normalized)


class InMemoryDerivedQdrant:
    """Minimal Qdrant-shaped test double; stores derived points only."""

    def __init__(self) -> None:
        self.points: dict[str, dict[str, object]] = {}
        self.vector_size: int | None = None
        self.available = True
        self.fail_after_successful_upserts: int | None = None
        self.successful_upserts = 0
        self.recreate_count = 0

    @staticmethod
    def point_id_for_evidence(evidence_id: UUID) -> str:
        return QdrantService.point_id_for_evidence(evidence_id)

    def _collection(self, *, vector_size: int, created: bool = False):
        return QdrantCollectionResult(
            availability=QdrantAvailability.AVAILABLE,
            collection_name="mine_trace_evidence",
            exists=True,
            compatible=True,
            expected_vector_size=vector_size,
            actual_vector_size=vector_size,
            expected_distance=QdrantDistance.COSINE,
            actual_distance=QdrantDistance.COSINE,
            created=created,
        )

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
        if self.vector_size is not None and self.vector_size != vector_size:
            return QdrantCollectionResult(
                availability=QdrantAvailability.AVAILABLE,
                collection_name="mine_trace_evidence",
                exists=True,
                compatible=False,
                expected_vector_size=vector_size,
                actual_vector_size=self.vector_size,
                expected_distance=QdrantDistance.COSINE,
                actual_distance=QdrantDistance.COSINE,
                reason="vector_size_mismatch",
            )
        created = self.vector_size is None
        self.vector_size = vector_size
        return self._collection(vector_size=vector_size, created=created)

    def recreate_collection(self, *, vector_size: int):
        if not self.available:
            return self.initialize_collection(vector_size=vector_size)
        self.points.clear()
        self.vector_size = vector_size
        self.successful_upserts = 0
        self.recreate_count += 1
        return self._collection(vector_size=vector_size, created=True)

    def delete_collection(self):
        if not self.available:
            return QdrantMutationResult(
                QdrantAvailability.UNAVAILABLE, False, reason="qdrant_unavailable"
            )
        self.points.clear()
        self.vector_size = None
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True)

    def upsert_vector(
        self, *, evidence_id, machine_id, component_id, evidence_type, vector
    ):
        point_id = self.point_id_for_evidence(evidence_id)
        if not self.available or (
            self.fail_after_successful_upserts is not None
            and self.successful_upserts >= self.fail_after_successful_upserts
        ):
            return QdrantMutationResult(
                QdrantAvailability.UNAVAILABLE,
                False,
                point_id=point_id,
                reason="qdrant_unavailable",
            )
        self.points[point_id] = {
            "vector": tuple(vector),
            "evidence_id": evidence_id,
            "machine_id": machine_id,
            "component_id": component_id,
            "evidence_type": evidence_type,
        }
        self.successful_upserts += 1
        return QdrantMutationResult(
            QdrantAvailability.AVAILABLE, True, point_id=point_id
        )

    def delete_vector(self, *, evidence_id):
        point_id = self.point_id_for_evidence(evidence_id)
        if not self.available:
            return QdrantMutationResult(
                QdrantAvailability.UNAVAILABLE,
                False,
                point_id=point_id,
                reason="qdrant_unavailable",
            )
        self.points.pop(point_id, None)
        return QdrantMutationResult(
            QdrantAvailability.AVAILABLE, True, point_id=point_id
        )


def canonical_snapshot(session_factory, evidence_id: UUID) -> dict[str, object]:
    with session_factory() as session:
        row = session.get(EvidenceEventRecord, evidence_id)
        assert row is not None
        return {
            "id": row.id,
            "machine_id": row.machine_id,
            "component_id": row.component_id,
            "source_type": row.source_type,
            "original_source_record_id": row.original_source_record_id,
            "original_timestamp": row.original_timestamp,
            "canonical_event_type": row.canonical_event_type,
            "canonical_payload": deepcopy(row.canonical_payload),
            "raw_source_payload": deepcopy(row.raw_source_payload),
            "provenance": deepcopy(row.provenance),
        }


def make_service(
    tmp_path, *, count: int = 1, batch_size: int = 2, observability: MLAIObservability | None = None
):
    settings = Settings(
        environment="test",
    )
    engine = create_sqlite_test_engine(tmp_path / 'indexing.db')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    machine_id = uuid4()
    evidence_ids: list[UUID] = []
    with session_factory() as session:
        session.add(MachineRecord(id=machine_id, asset_code="MT-INDEX"))
        session.flush()
        for index in range(count):
            evidence_id = uuid4()
            evidence_ids.append(evidence_id)
            session.add(
                EvidenceEventRecord(
                    id=evidence_id,
                    machine_id=machine_id,
                    source_machine_id=machine_id,
                    component_id=None,
                    source_type="HUMAN_OBSERVATION",
                    original_source_record_id=f"obs-{index}",
                    original_timestamp=datetime(2026, 10, 3, index, tzinfo=UTC),
                    canonical_event_type="OPERATOR_NOTE",
                    canonical_payload={"note": f"hydraulic noise observation {index}"},
                    raw_source_payload={"source": "unchanged"},
                    provenance={"system": "test"},
                )
            )
        session.commit()

    def uow_factory():
        return SQLAlchemyUnitOfWork(session_factory)

    embedding = DeterministicEmbeddingProvider()
    qdrant = InMemoryDerivedQdrant()
    service = CanonicalEvidenceIndexingService(
        uow_factory,
        embedding,
        qdrant,  # type: ignore[arg-type]
        batch_size=batch_size,
        observability=observability,
    )
    return service, embedding, qdrant, session_factory, evidence_ids


def test_canonical_evidence_indexes_with_deterministic_point_identity(tmp_path) -> None:
    service, _embedding, qdrant, _sessions, evidence_ids = make_service(tmp_path)
    evidence_id = evidence_ids[0]

    result = service.index_evidence(evidence_id)

    assert result.state is SemanticIndexingState.INDEXED
    assert result.point_id == str(evidence_id)
    assert tuple(qdrant.points) == (str(evidence_id),)
    assert qdrant.points[str(evidence_id)]["evidence_id"] == evidence_id


def test_repeated_indexing_is_idempotent_and_does_not_duplicate_points(tmp_path) -> None:
    service, _embedding, qdrant, _sessions, evidence_ids = make_service(tmp_path)
    evidence_id = evidence_ids[0]

    first = service.index_evidence(evidence_id)
    second = service.index_evidence(evidence_id)

    assert first.indexed and second.indexed
    assert len(qdrant.points) == 1
    assert first.point_id == second.point_id == str(evidence_id)


def test_reindex_reads_updated_semantic_text_from_canonical_storage(tmp_path) -> None:
    service, embedding, qdrant, sessions, evidence_ids = make_service(tmp_path)
    evidence_id = evidence_ids[0]
    service.index_evidence(evidence_id)
    first_vector = qdrant.points[str(evidence_id)]["vector"]

    # Simulate a canonical correction/migration outside the derived ML layer.
    with sessions() as session:
        row = session.get(EvidenceEventRecord, evidence_id)
        assert row is not None
        row.canonical_payload = {"note": "updated canonical hydraulic leak description"}
        session.commit()

    result = service.reindex_evidence(evidence_id)

    assert result.indexed
    assert len(qdrant.points) == 1
    assert qdrant.points[str(evidence_id)]["vector"] != first_vector
    assert "updated canonical hydraulic leak description" in embedding.calls[-1][0]


def test_remove_derived_vector_preserves_canonical_evidence(tmp_path) -> None:
    service, _embedding, qdrant, sessions, evidence_ids = make_service(tmp_path)
    evidence_id = evidence_ids[0]
    service.index_evidence(evidence_id)
    before = canonical_snapshot(sessions, evidence_id)

    result = service.remove_derived_vector(evidence_id)

    assert result.state is SemanticIndexingState.REMOVED
    assert str(evidence_id) not in qdrant.points
    assert canonical_snapshot(sessions, evidence_id) == before


def test_full_qdrant_collection_rebuilds_from_canonical_evidence(tmp_path) -> None:
    service, _embedding, qdrant, sessions, evidence_ids = make_service(
        tmp_path, count=5, batch_size=2
    )
    # Simulate stale/foreign derived contents. Rebuild must discard them.
    qdrant.points["00000000-0000-0000-0000-000000000001"] = {"vector": (9.0,)}
    before = {evidence_id: canonical_snapshot(sessions, evidence_id) for evidence_id in evidence_ids}

    result = service.rebuild_qdrant_index()

    assert result.state is SemanticRebuildState.REBUILT
    assert result.canonical_records_seen == 5
    assert result.eligible_documents == 5
    assert result.indexed == 5
    assert result.failed == 0
    assert result.collection_recreated is True
    assert result.vector_size == 3
    assert qdrant.recreate_count == 1
    assert set(qdrant.points) == {str(evidence_id) for evidence_id in evidence_ids}
    assert {evidence_id: canonical_snapshot(sessions, evidence_id) for evidence_id in evidence_ids} == before


def test_failed_qdrant_write_is_observable_and_canonical_truth_is_unchanged(tmp_path) -> None:
    observability = MLAIObservability()
    service, _embedding, qdrant, sessions, evidence_ids = make_service(
        tmp_path, count=3, batch_size=3, observability=observability
    )
    before = {evidence_id: canonical_snapshot(sessions, evidence_id) for evidence_id in evidence_ids}
    qdrant.fail_after_successful_upserts = 1

    result = service.rebuild_qdrant_index()

    assert result.state is SemanticRebuildState.PARTIAL
    assert result.indexed == 1
    assert result.failed == 2
    assert result.reason == "qdrant_unavailable"
    assert observability.snapshot().indexing_failures == 2
    assert {evidence_id: canonical_snapshot(sessions, evidence_id) for evidence_id in evidence_ids} == before

    # Retry is possible because canonical rows remain the source of truth.
    qdrant.fail_after_successful_upserts = None
    retry = service.rebuild_qdrant_index()
    assert retry.state is SemanticRebuildState.REBUILT
    assert set(qdrant.points) == {str(evidence_id) for evidence_id in evidence_ids}


def test_batch_index_uses_canonical_source_and_reports_missing_ids(tmp_path) -> None:
    service, _embedding, qdrant, _sessions, evidence_ids = make_service(
        tmp_path, count=2, batch_size=8
    )
    missing = uuid4()

    result = service.batch_index((evidence_ids[0], missing, evidence_ids[1], evidence_ids[0]))

    assert result.requested == 3  # duplicate request is intentionally deduplicated
    assert result.indexed == 2
    assert result.not_found == 1
    assert set(qdrant.points) == {str(evidence_id) for evidence_id in evidence_ids}
