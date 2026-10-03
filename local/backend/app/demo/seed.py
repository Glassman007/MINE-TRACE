"""Idempotent deterministic demo seeding using real backend services.

Only demo_mode may call this module. Canonical data is written to SQLite, incident
association uses the real deterministic linker, verification uses the persisted
NO_EVENT rule, session close creates the immutable report/outbox, and a fake
central acknowledgement drives the real conflict path. Semantic indexing uses
the configured derived Qdrant path when that optional dependency is available.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.demo.fixtures import COMPONENT_IDS, DEMO_ANCHOR, DEMO_COMPONENTS, DEMO_MACHINE, DEMO_MACHINE_ID
from app.domain.enums import IncidentStatus, SyncOutboxState
from app.integrations.embeddings.factory import build_embedding_provider
from app.integrations.qdrant import QdrantService
from app.models import ComponentRecord, EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.ingestion import HumanObservationInput, MachineEventInput, MaintenanceRecordInput
from app.schemas.sync import SyncAcknowledgement, SyncAcknowledgementStatus
from app.services.handover import HandoverService
from app.services.ingestion import IngestionService
from app.services.return_to_service import ReturnToServiceService
from app.services.semantic_indexing import CanonicalEvidenceIndexingService
from app.services.sessions import OperatingSessionService
from app.services.sync import SyncOutboxService, SyncStatusService
from app.services.verification import VerificationService


class DemoSeedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DemoSeedSummary:
    machine_id: str
    component_count: int
    primary_incident_id: str
    unresolved_incident_id: str
    closed_session_id: str
    active_session_id: str
    report_id: str
    sync_package_id: str
    sync_state: str
    semantic_index_state: str
    return_to_service_state: str


class _ConflictTransport:
    def __init__(self, at: datetime) -> None:
        self._at = at
    def send(self, envelope):  # type: ignore[no-untyped-def]
        return SyncAcknowledgement(
            schema_version=envelope.schema_version,
            package_id=envelope.package_id,
            status=SyncAcknowledgementStatus.CONFLICT,
            central_revision=envelope.local_revision + 1,
            acknowledged_at=self._at,
            message="Demo central revision conflict",
            resolution_metadata={"demo": True, "resolution": "operator review required"},
        )


def _factory(settings: Settings):
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    return engine, sessions, lambda: SQLAlchemyUnitOfWork(sessions)


def _guard(settings: Settings) -> None:
    if not settings.demo_mode:
        raise DemoSeedError("demo seeding requires MINE_TRACE_DEMO_MODE=true")
    if settings.environment == "production":
        raise DemoSeedError("demo seeding is disabled in production")
    if settings.local_machine_id != DEMO_MACHINE_ID:
        raise DemoSeedError("demo mode local_machine_id must resolve to the demo machine")


def _reset_all(session_factory: Callable[[], Session]) -> None:
    with session_factory.begin() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())


def _ensure_identity(uow_factory) -> None:  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        if uow.machines.get(DEMO_MACHINE_ID) is None:
            uow.machines.add(MachineRecord(**DEMO_MACHINE))
            uow.flush()
        for key, display_name, component_type in DEMO_COMPONENTS:
            component_id = COMPONENT_IDS[key]
            if uow.components.get(component_id) is None:
                uow.components.add(ComponentRecord(
                    id=component_id, machine_id=DEMO_MACHINE_ID,
                    display_name=display_name, component_type=component_type,
                    manufacturer=None, model=None,
                ))
        uow.commit()


def _existing_primary(session_factory: Callable[[], Session]) -> EvidenceEventRecord | None:
    with session_factory() as session:
        return session.scalar(select(EvidenceEventRecord).where(
            EvidenceEventRecord.original_source_record_id == "DEMO-EXC204-HYD-OBS-001"
        ))


def _semantic_rebuild(settings: Settings, uow_factory) -> str:  # type: ignore[no-untyped-def]
    try:
        provider = build_embedding_provider(settings)
        qdrant = QdrantService.from_settings(settings)
        result = CanonicalEvidenceIndexingService(uow_factory, provider, qdrant).rebuild_qdrant_index()
        return result.state.value
    except Exception as exc:
        # Derived semantic failure never invalidates the canonical demo.
        return f"DEGRADED:{type(exc).__name__}"


def _summary(settings: Settings, session_factory: Callable[[], Session], semantic_state: str) -> DemoSeedSummary:
    uow_factory = lambda: SQLAlchemyUnitOfWork(session_factory)
    with uow_factory() as uow:
        sessions = list(uow.operating_sessions.list_for_machine(DEMO_MACHINE_ID))
        closed = [item for item in sessions if item.ended_at is not None]
        active = [item for item in sessions if item.ended_at is None]
        if not closed or not active:
            raise DemoSeedError("demo sessions are incomplete")
        closed_record = closed[-1]
        active_record = active[-1]
        report = uow.machine_session_reports.get_for_session(closed_record.session_id)
        if report is None:
            raise DemoSeedError("demo report is missing")
        outbox = list(uow.sync_outbox.list_for_machine(DEMO_MACHINE_ID))
        if not outbox:
            raise DemoSeedError("demo sync package is missing")
        primary = uow.evidence_events.get_by_source_identity("HUMAN_OBSERVATION", "DEMO-EXC204-HYD-OBS-001")
        unresolved = uow.evidence_events.get_by_source_identity("HUMAN_OBSERVATION", "DEMO-EXC204-COOL-001")
        if primary is None or unresolved is None:
            raise DemoSeedError("demo evidence is incomplete")
        primary_links = list(uow.incident_evidence_links.list_active_for_evidence(primary.id))
        unresolved_links = list(uow.incident_evidence_links.list_active_for_evidence(unresolved.id))
        if len(primary_links) != 1 or len(unresolved_links) != 1:
            raise DemoSeedError("demo incident links are incomplete")
        rts = ReturnToServiceService(settings, uow_factory).evaluate()
        return DemoSeedSummary(
            machine_id=str(DEMO_MACHINE_ID), component_count=len(DEMO_COMPONENTS),
            primary_incident_id=str(primary_links[0].incident_id),
            unresolved_incident_id=str(unresolved_links[0].incident_id),
            closed_session_id=str(closed_record.session_id), active_session_id=str(active_record.session_id),
            report_id=str(report.report_id), sync_package_id=str(outbox[-1].package_id),
            sync_state=outbox[-1].state.value, semantic_index_state=semantic_state,
            return_to_service_state=rts.state.value,
        )


def seed_demo(settings: Settings | None = None, *, reset: bool = False) -> DemoSeedSummary:
    settings = settings or get_settings()
    _guard(settings)
    engine, session_factory, uow_factory = _factory(settings)
    try:
        if reset:
            _reset_all(session_factory)
        _ensure_identity(uow_factory)

        if _existing_primary(session_factory) is not None:
            semantic_state = _semantic_rebuild(settings, uow_factory)
            return _summary(settings, session_factory, semantic_state)

        anchor = DEMO_ANCHOR
        session_service = OperatingSessionService(uow_factory, settings, clock=lambda: anchor)
        ingestion = IngestionService(uow_factory, settings=settings)
        verification = VerificationService(settings, uow_factory, clock=lambda: anchor)

        previous = session_service.open_session(started_at=anchor - timedelta(hours=8))

        # Historical semantic candidate: canonical SQLite evidence, intentionally not
        # attached to the current incident or operating session.
        with uow_factory() as uow:
            uow.evidence_events.add(EvidenceEventRecord(
                id=__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "mine-trace-demo:previous-similar"),
                machine_id=DEMO_MACHINE_ID, component_id=COMPONENT_IDS["hydraulic_pump"], session_id=None,
                source_type="HUMAN_OBSERVATION", original_source_record_id="DEMO-EXC204-HYD-HISTORY-001",
                original_timestamp=anchor - timedelta(days=7), ingestion_timestamp=anchor - timedelta(days=7),
                canonical_event_type="HYDRAULIC_PRESSURE_LOW",
                canonical_payload={"observation": "Hydraulic response slowed and the pump whined under load."},
                raw_source_payload={"note": "slow boom response; pump whine"},
                provenance={"source_system": "demo-history", "demo_role": "semantic candidate"},
            ))
            uow.commit()

        primary_evidence_id = ingestion.ingest_human_observation(HumanObservationInput(
            machine_id=DEMO_MACHINE_ID, component_id=COMPONENT_IDS["hydraulic_pump"], session_id=previous.session_id,
            original_source_record_id="DEMO-EXC204-HYD-OBS-001", original_timestamp=anchor - timedelta(hours=5),
            observation_type="HYDRAULIC_PRESSURE_LOW",
            payload={"observation": "Operator observed slow boom response and hydraulic pump whine under load."},
            raw_payload={"note": "boom slow; pump whining"},
            provenance={"source_system": "demo-operator-console", "operator": "demo-operator"},
        ))
        ingestion.ingest_machine_event(MachineEventInput(
            machine_id=DEMO_MACHINE_ID, component_id=COMPONENT_IDS["hydraulic_pump"], session_id=previous.session_id,
            original_source_record_id="DEMO-EXC204-HYD-SENSOR-001", original_timestamp=anchor - timedelta(hours=4, minutes=50),
            event_type="HYDRAULIC_PRESSURE_LOW",
            payload={"pressure_kpa": 17650, "expected_min_kpa": 19000},
            raw_payload={"pressure_mpa": 17.65},
            provenance={"source_system": "demo-pressure-sensor", "channel": "pump-discharge"},
        ))
        ingestion.ingest_maintenance_record(MaintenanceRecordInput(
            machine_id=DEMO_MACHINE_ID, component_id=COMPONENT_IDS["hydraulic_pump"], session_id=previous.session_id,
            original_source_record_id="DEMO-EXC204-HYD-WO-001", original_timestamp=anchor - timedelta(hours=4),
            record_type="HYDRAULIC_PRESSURE_LOW",
            payload={"action": "Hydraulic return filter replaced and relief-valve setting inspected", "work_order": "WO-DEMO-204-17"},
            raw_payload={"technician_note": "filter replaced; relief setting checked"},
            provenance={"source_system": "demo-cmms", "technician": "demo-tech-1"},
        ))

        with uow_factory() as uow:
            links = list(uow.incident_evidence_links.list_active_for_evidence(primary_evidence_id))
            if len(links) != 1:
                raise DemoSeedError("primary demo evidence did not produce one incident")
            primary_incident_id = links[0].incident_id

        verification.start_verification(primary_incident_id, started_at=anchor - timedelta(hours=3, minutes=45))
        verification.evaluate_due(as_of=anchor - timedelta(hours=3, minutes=10))
        closed = session_service.close_session(
            previous.session_id, ended_at=anchor - timedelta(hours=3), operating_hours=5.0
        )

        # Send through the real outbox service with a deterministic fake central conflict.
        with uow_factory() as uow:
            queued = list(uow.sync_outbox.list_for_machine(DEMO_MACHINE_ID))[-1]
            queued_id = queued.id
        SyncOutboxService(
            uow_factory, settings,
            transport=_ConflictTransport(anchor - timedelta(hours=2, minutes=55)),
            clock=lambda: anchor - timedelta(hours=2, minutes=55),
        ).send_item(queued_id)

        current = session_service.open_session(started_at=anchor - timedelta(hours=2, minutes=30))
        ingestion.ingest_human_observation(HumanObservationInput(
            machine_id=DEMO_MACHINE_ID, component_id=COMPONENT_IDS["cooling"], session_id=current.session_id,
            original_source_record_id="DEMO-EXC204-COOL-001", original_timestamp=anchor - timedelta(hours=1),
            observation_type="COOLANT_LEVEL_LOW",
            payload={"observation": "Cooling-system level requires inspection before return to normal operation."},
            raw_payload={"note": "coolant sight glass below normal range"},
            provenance={"source_system": "demo-operator-console", "operator": "demo-operator"},
        ))
        HandoverService(uow_factory, clock=lambda: anchor).create_handover(created_at=anchor)

        semantic_state = _semantic_rebuild(settings, uow_factory)
        summary = _summary(settings, session_factory, semantic_state)
        # Exercise the deterministic status services as an acceptance assertion.
        if SyncStatusService(uow_factory, settings).get_status().conflict_count < 1:
            raise DemoSeedError("demo sync conflict was not persisted")
        if closed.report.evidence_manifest.entries == []:
            raise DemoSeedError("demo session report has an empty EvidenceManifest")
        return summary
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed/reset the deterministic MINE-TRACE local demo")
    parser.add_argument("--reset", action="store_true", help="clear demo-mode application tables before reseeding")
    args = parser.parse_args()
    summary = seed_demo(reset=args.reset)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
