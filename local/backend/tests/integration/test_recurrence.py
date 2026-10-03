from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.models import (
    ComponentRecord,
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.ingestion import MachineEventInput
from app.services.incident_linking import IncidentLinkingService
from app.services.ingestion import IngestionService
from app.services.recurrence import RecurrenceService, RecurrenceStage


class InjectedRecurrenceFailure(RuntimeError):
    pass


@pytest.fixture
def recurrence_env(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'recurrence.db'}",
        sqlite_wal_enabled=False,
        incident_linking_window_minutes=60,
        incident_linking_rule_identifier="test.recurrence-link.v1",
        incident_linking_rule_name="Test recurrence linking rule",
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_id = uuid4()
    component_id = uuid4()
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add(ComponentRecord(id=component_id, machine_id=machine_id))

    recurrence = RecurrenceService()
    linker = IncidentLinkingService(settings, recurrence_service=recurrence)
    ingestion = IngestionService(
        lambda: SQLAlchemyUnitOfWork(factory),
        incident_linking_service=linker,
    )

    yield {
        "settings": settings,
        "engine": engine,
        "factory": factory,
        "machine_id": machine_id,
        "component_id": component_id,
        "recurrence": recurrence,
        "linker": linker,
        "ingestion": ingestion,
    }

    engine.dispose()


def _request(
    env: dict[str, Any],
    *,
    record_id: str,
    at: datetime,
    event_type: str = "HYDRAULIC_PRESSURE_WARNING",
) -> MachineEventInput:
    return MachineEventInput(
        machine_id=env["machine_id"],
        component_id=env["component_id"],
        original_source_record_id=record_id,
        original_timestamp=at,
        event_type=event_type,
        payload={"event_type": event_type, "record_id": record_id},
        raw_payload={"raw_event_type": event_type, "source_record": record_id},
        provenance={"source_system": "recurrence-test"},
    )


def _count(factory: sessionmaker[Session], model: type[Any]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def _incident_id_for(factory: sessionmaker[Session], evidence_id: UUID) -> UUID:
    with factory() as session:
        incident_id = session.scalar(
            select(IncidentEvidenceLinkRecord.incident_id).where(
                IncidentEvidenceLinkRecord.evidence_event_id == evidence_id,
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
        )
        assert incident_id is not None
        return incident_id


def _reconstruct(env: dict[str, Any], incident_id: UUID):
    with SQLAlchemyUnitOfWork(env["factory"]) as uow:
        return env["recurrence"].reconstruct_occurrences(uow, incident_id)


def test_exact_replay_reuses_evidence_and_records_no_recurrence(
    recurrence_env: dict[str, Any],
) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    request = _request(recurrence_env, record_id="same-source-record", at=at)

    first_id = recurrence_env["ingestion"].ingest_machine_event(request)
    replay_id = recurrence_env["ingestion"].ingest_machine_event(request)

    assert replay_id == first_id
    assert _count(recurrence_env["factory"], EvidenceEventRecord) == 1
    incident_id = _incident_id_for(recurrence_env["factory"], first_id)
    reconstruction = _reconstruct(recurrence_env, incident_id)
    assert reconstruction.occurrence_count == 1
    assert reconstruction.recurrence_evidence_ids == ()

    with recurrence_env["factory"]() as session:
        recurrence_audits = session.scalars(
            select(IncidentAuditEventRecord).where(
                IncidentAuditEventRecord.action
                == IncidentAuditAction.RECURRENCE_RECORDED
            )
        ).all()
        assert recurrence_audits == []


def test_genuine_repeated_event_creates_new_evidence_and_recurrence_link(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    first_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="occurrence-1", at=base)
    )
    incident_id = _incident_id_for(recurrence_env["factory"], first_id)

    # VERIFIED -> RECURRED is an explicitly allowed recurrence transition.  Direct
    # seeding here isolates recurrence behavior; verification service logic is not
    # part of this implementation step.
    with recurrence_env["factory"].begin() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        incident.status = IncidentStatus.VERIFIED

    second_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(
            recurrence_env,
            record_id="occurrence-2",
            at=base + timedelta(minutes=15),
        )
    )

    assert second_id != first_id
    assert _count(recurrence_env["factory"], EvidenceEventRecord) == 2
    assert _incident_id_for(recurrence_env["factory"], second_id) == incident_id

    with recurrence_env["factory"]() as session:
        link = session.scalar(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.evidence_event_id == second_id,
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
        )
        incident = session.get(IncidentRecord, incident_id)
        assert link is not None
        assert link.relationship_type == IncidentEvidenceRelationshipType.RECURRENCE
        assert incident is not None
        assert incident.status == IncidentStatus.RECURRED


def test_three_genuine_occurrences_are_three_raw_evidence_events(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    evidence_ids = [
        recurrence_env["ingestion"].ingest_machine_event(
            _request(
                recurrence_env,
                record_id=f"three-{index}",
                at=base + timedelta(minutes=index * 10),
            )
        )
        for index in range(3)
    ]

    incident_ids = {
        _incident_id_for(recurrence_env["factory"], evidence_id)
        for evidence_id in evidence_ids
    }
    assert len(incident_ids) == 1
    assert _count(recurrence_env["factory"], EvidenceEventRecord) == 3

    incident_id = next(iter(incident_ids))
    reconstruction = _reconstruct(recurrence_env, incident_id)
    assert reconstruction.occurrence_count == 3
    assert reconstruction.evidence_ids == tuple(evidence_ids)
    assert reconstruction.recurrence_evidence_ids == tuple(evidence_ids[1:])


def test_occurrence_reconstruction_uses_original_timestamp_order(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    later_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="chronology-later", at=base + timedelta(minutes=20))
    )
    earlier_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="chronology-earlier", at=base + timedelta(minutes=10))
    )
    latest_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="chronology-latest", at=base + timedelta(minutes=30))
    )

    incident_id = _incident_id_for(recurrence_env["factory"], later_id)
    reconstruction = _reconstruct(recurrence_env, incident_id)

    assert reconstruction.occurrence_count == 3
    assert reconstruction.evidence_ids == (earlier_id, later_id, latest_id)


def test_replay_after_multiple_occurrences_does_not_increase_reconstruction(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    requests = [
        _request(
            recurrence_env,
            record_id=f"multi-{index}",
            at=base + timedelta(minutes=index * 10),
        )
        for index in range(3)
    ]
    evidence_ids = [
        recurrence_env["ingestion"].ingest_machine_event(request)
        for request in requests
    ]
    incident_id = _incident_id_for(recurrence_env["factory"], evidence_ids[0])

    before_audits = _count(recurrence_env["factory"], IncidentAuditEventRecord)
    replay_id = recurrence_env["ingestion"].ingest_machine_event(requests[1])
    after = _reconstruct(recurrence_env, incident_id)

    assert replay_id == evidence_ids[1]
    assert after.occurrence_count == 3
    assert _count(recurrence_env["factory"], EvidenceEventRecord) == 3
    assert _count(recurrence_env["factory"], IncidentAuditEventRecord) == before_audits


def test_recurrence_audit_event_identifies_raw_occurrence(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    first_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="audit-repeat-1", at=base)
    )
    second_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(
            recurrence_env,
            record_id="audit-repeat-2",
            at=base + timedelta(minutes=5),
        )
    )
    incident_id = _incident_id_for(recurrence_env["factory"], first_id)

    with recurrence_env["factory"]() as session:
        audit = session.scalar(
            select(IncidentAuditEventRecord).where(
                IncidentAuditEventRecord.incident_id == incident_id,
                IncidentAuditEventRecord.action
                == IncidentAuditAction.RECURRENCE_RECORDED,
            )
        )
        assert audit is not None
        assert audit.payload["evidence_event_id"] == str(second_id)
        assert audit.payload["relationship_type"] == "RECURRENCE"
        assert audit.payload["rule_identifier"] == "test.recurrence-link.v1"


def test_recurrence_failure_rolls_back_evidence_link_audits_and_status(
    recurrence_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    first_id = recurrence_env["ingestion"].ingest_machine_event(
        _request(recurrence_env, record_id="rollback-1", at=base)
    )
    incident_id = _incident_id_for(recurrence_env["factory"], first_id)

    with recurrence_env["factory"].begin() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        incident.status = IncidentStatus.VERIFYING

    def fault_hook(stage: RecurrenceStage) -> None:
        if stage == RecurrenceStage.RECURRENCE_AUDIT_APPENDED:
            raise InjectedRecurrenceFailure(stage.value)

    failing_recurrence = RecurrenceService(fault_hook=fault_hook)
    failing_linker = IncidentLinkingService(
        recurrence_env["settings"],
        recurrence_service=failing_recurrence,
    )
    failing_ingestion = IngestionService(
        lambda: SQLAlchemyUnitOfWork(recurrence_env["factory"]),
        incident_linking_service=failing_linker,
    )

    audits_before = _count(recurrence_env["factory"], IncidentAuditEventRecord)
    with pytest.raises(InjectedRecurrenceFailure):
        failing_ingestion.ingest_machine_event(
            _request(
                recurrence_env,
                record_id="rollback-2",
                at=base + timedelta(minutes=10),
            )
        )

    with recurrence_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        assert incident.status == IncidentStatus.VERIFYING

        evidence = session.scalars(
            select(EvidenceEventRecord).order_by(EvidenceEventRecord.id)
        ).all()
        assert [item.id for item in evidence] == [first_id]

        links = session.scalars(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.incident_id == incident_id
            )
        ).all()
        assert len(links) == 1
        assert links[0].evidence_event_id == first_id
        assert links[0].relationship_type == IncidentEvidenceRelationshipType.RELATED

    assert _count(recurrence_env["factory"], IncidentAuditEventRecord) == audits_before
