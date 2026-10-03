"""Integration proof that ML-derived state is disposable, not canonical."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.integrations.semantic import SemanticIndexHit
from app.models import EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork


class DisposableDerivedSemanticState:
    """Test-only stand-in for a complete disposable Qdrant collection."""

    def __init__(self) -> None:
        self.points: dict[UUID, tuple[list[float], UUID, UUID | None]] = {}

    def upsert_evidence(
        self,
        *,
        evidence_id: UUID,
        machine_id: UUID,
        component_id: UUID | None,
        vector: list[float],
    ) -> None:
        self.points[evidence_id] = (vector, machine_id, component_id)

    def search(
        self,
        *,
        vector: list[float],
        machine_id: UUID,
        component_id: UUID | None,
        top_k: int,
        min_similarity: float | None,
    ) -> list[SemanticIndexHit]:
        del vector, machine_id, component_id, top_k, min_similarity
        return [SemanticIndexHit(evidence_id=evidence_id, score=1.0) for evidence_id in self.points]

    def delete_complete_collection(self) -> None:
        self.points.clear()


def test_deleting_all_derived_semantic_state_preserves_canonical_truth(tmp_path) -> None:
    settings = Settings(
        environment="test",
    )
    engine = create_sqlite_test_engine(tmp_path / 'authority-boundary.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_id = uuid4()
    evidence_id = uuid4()
    occurred_at = datetime(2026, 10, 3, 2, 30, tzinfo=timezone.utc)

    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id, asset_code="MT-BOUNDARY-001"))
        session.flush()
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=None,
                source_type="MACHINE_EVENT",
                original_source_record_id="boundary-event-001",
                original_timestamp=occurred_at,
                ingestion_timestamp=occurred_at,
                canonical_event_type="WARNING",
                canonical_payload={"warning": "hydraulic_pressure"},
                raw_source_payload={"raw": True},
                provenance={"source_system": "boundary-test"},
            )
        )

    derived = DisposableDerivedSemanticState()
    derived.upsert_evidence(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=None,
        vector=[0.1, 0.2, 0.3],
    )
    assert evidence_id in derived.points

    # Simulates deleting the entire Qdrant collection / all ML-derived state.
    derived.delete_complete_collection()
    assert derived.points == {}

    # Canonical truth still exists independently in the authoritative store.
    with SQLAlchemyUnitOfWork(factory) as uow:
        canonical = uow.evidence_events.get(evidence_id)
        assert canonical is not None
        assert canonical.machine_id == machine_id
        assert canonical.canonical_event_type == "WARNING"
        assert canonical.canonical_payload == {"warning": "hydraulic_pressure"}
        assert canonical.provenance == {"source_system": "boundary-test"}

    engine.dispose()
