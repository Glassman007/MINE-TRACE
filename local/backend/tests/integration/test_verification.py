from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.core.time import normalize_to_utc
from app.db.base import Base
from app.db.session import create_database_engine
from app.domain.enums import (
    IncidentAuditAction,
    IncidentStatus,
    VerificationRunResult,
)
from app.domain.lifecycle import InvalidIncidentTransition, validate_incident_transition
from app.main import app
from app.models import (
    ComponentRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationEvidenceRecord,
    VerificationRunRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.ingestion import MachineEventInput
from app.services.incident_linking import IncidentLinkingService
from app.services.ingestion import IngestionService
from app.services.verification import VerificationService


@pytest.fixture
def verification_env(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'verification.db'}",
        sqlite_wal_enabled=False,
        incident_linking_window_minutes=120,
        verification_window_minutes=30,
        verification_rule_identifier="test.no-event.v1",
        verification_rule_name="Test NO_EVENT rule",
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

    linker = IncidentLinkingService(settings)
    ingestion = IngestionService(
        lambda: SQLAlchemyUnitOfWork(factory),
        incident_linking_service=linker,
    )
    verification = VerificationService(
        settings,
        lambda: SQLAlchemyUnitOfWork(factory),
    )

    yield {
        "settings": settings,
        "engine": engine,
        "factory": factory,
        "machine_id": machine_id,
        "component_id": component_id,
        "ingestion": ingestion,
        "verification": verification,
        "db_path": tmp_path / "verification.db",
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
        payload={"record": record_id},
        raw_payload={"source_record": record_id},
        provenance={"source_system": "verification-test"},
    )


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


def _seed_open_incident(env: dict[str, Any], *, at: datetime) -> tuple[UUID, UUID]:
    evidence_id = env["ingestion"].ingest_machine_event(
        _request(env, record_id=f"initial-{uuid4()}", at=at)
    )
    return _incident_id_for(env["factory"], evidence_id), evidence_id


def test_open_to_verifying_starts_persisted_absolute_window(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)

    run = verification_env["verification"].start_verification(
        incident_id,
        started_at=base + timedelta(minutes=1),
    )

    assert run.started_at == base + timedelta(minutes=1)
    assert run.window_ends_at == base + timedelta(minutes=31)
    assert run.window_minutes == 30
    assert run.result is None

    with verification_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        persisted = session.get(VerificationRunRecord, run.id)
        assert incident is not None
        assert incident.status == IncidentStatus.VERIFYING
        assert persisted is not None
        assert normalize_to_utc(persisted.window_ends_at) == run.window_ends_at


def test_open_to_verified_is_explicitly_rejected() -> None:
    with pytest.raises(InvalidIncidentTransition):
        validate_incident_transition(IncidentStatus.OPEN, IncidentStatus.VERIFIED)


def test_verifying_to_verified_when_no_event_window_succeeds(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id, started_at=base + timedelta(minutes=1)
    )

    completed = verification_env["verification"].evaluate_due(
        as_of=run.window_ends_at
    )
    assert len(completed) == 1
    assert completed[0].result == VerificationRunResult.SUCCEEDED
    assert completed[0].completed_at == run.window_ends_at
    assert completed[0].evidence_event_ids == ()

    with verification_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        assert incident.status == IncidentStatus.VERIFIED


def test_verifying_to_recurred_persists_verification_evidence(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id, started_at=base + timedelta(minutes=1)
    )

    recurrence_id = verification_env["ingestion"].ingest_machine_event(
        _request(
            verification_env,
            record_id="verification-recurrence",
            at=base + timedelta(minutes=10),
        )
    )

    with verification_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        persisted_run = session.get(VerificationRunRecord, run.id)
        verification_evidence = session.scalar(
            select(VerificationEvidenceRecord).where(
                VerificationEvidenceRecord.verification_run_id == run.id,
                VerificationEvidenceRecord.evidence_event_id == recurrence_id,
            )
        )
        assert incident is not None
        assert incident.status == IncidentStatus.RECURRED
        assert persisted_run is not None
        assert persisted_run.result == VerificationRunResult.RECURRENCE_DETECTED
        assert persisted_run.completed_at is not None
        assert verification_evidence is not None


def test_verified_to_recurred_on_later_genuine_event(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id, started_at=base + timedelta(minutes=1)
    )
    verification_env["verification"].evaluate_due(as_of=run.window_ends_at)

    verification_env["ingestion"].ingest_machine_event(
        _request(
            verification_env,
            record_id="after-verified",
            # Outside verification window but still inside incident-linking window.
            at=base + timedelta(minutes=40),
        )
    )

    with verification_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        assert incident.status == IncidentStatus.RECURRED


def test_recurred_to_verifying_starts_reverification(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    first_run = verification_env["verification"].start_verification(
        incident_id, started_at=base + timedelta(minutes=1)
    )
    verification_env["ingestion"].ingest_machine_event(
        _request(
            verification_env,
            record_id="reverify-recurrence",
            at=base + timedelta(minutes=10),
        )
    )

    second = verification_env["verification"].start_verification(
        incident_id,
        started_at=base + timedelta(minutes=15),
    )
    assert second.id != first_run.id

    with verification_env["factory"]() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        assert incident.status == IncidentStatus.VERIFYING


def test_backend_restart_does_not_restart_verification_window(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id,
        started_at=base + timedelta(minutes=2),
    )
    original_end = run.window_ends_at

    # Simulate process/backend restart: dispose all old connections and rebuild the
    # engine/session/service from the persisted SQLite file. Also change runtime
    # settings to prove an in-flight run does not use a newly configured duration.
    verification_env["engine"].dispose()
    restarted_settings = Settings(
        environment="test",
        database_url=f"sqlite:///{verification_env['db_path']}",
        sqlite_wal_enabled=False,
        verification_window_minutes=999,
        verification_rule_identifier="different.rule.for.new-runs.v2",
        verification_rule_name="Changed runtime rule",
    )
    restarted_engine = create_database_engine(restarted_settings)
    restarted_factory = sessionmaker(
        bind=restarted_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    restarted_service = VerificationService(
        restarted_settings,
        lambda: SQLAlchemyUnitOfWork(restarted_factory),
    )
    try:
        restored = restarted_service.get_run(run.id)
        assert restored.started_at == run.started_at
        assert restored.window_ends_at == original_end
        assert restored.window_minutes == 30

        # Still not due one second before the persisted absolute boundary.
        assert restarted_service.evaluate_due(
            as_of=original_end - timedelta(seconds=1)
        ) == ()

        due = restarted_service.evaluate_due(as_of=original_end)
        assert len(due) == 1
        assert due[0].result == VerificationRunResult.SUCCEEDED
    finally:
        restarted_engine.dispose()


def test_original_absolute_window_is_retained_after_restart(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id, started_at=base
    )

    with verification_env["factory"]() as session:
        persisted = session.get(VerificationRunRecord, run.id)
        assert persisted is not None
        assert normalize_to_utc(persisted.started_at) == base
        assert normalize_to_utc(persisted.window_ends_at) == base + timedelta(minutes=30)


def test_status_change_audit_events_are_persisted_for_verification(
    verification_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)
    incident_id, _ = _seed_open_incident(verification_env, at=base)
    run = verification_env["verification"].start_verification(
        incident_id, started_at=base + timedelta(minutes=1)
    )
    verification_env["verification"].evaluate_due(as_of=run.window_ends_at)

    with verification_env["factory"]() as session:
        audits = session.scalars(
            select(IncidentAuditEventRecord)
            .where(
                IncidentAuditEventRecord.incident_id == incident_id,
                IncidentAuditEventRecord.action == IncidentAuditAction.STATUS_CHANGED,
            )
            .order_by(IncidentAuditEventRecord.occurred_at, IncidentAuditEventRecord.id)
        ).all()
        transitions = [
            (audit.payload["from_status"], audit.payload["to_status"])
            for audit in audits
            if audit.payload.get("verification_run_id") == str(run.id)
        ]
        assert transitions == [("OPEN", "VERIFYING"), ("VERIFYING", "VERIFIED")]


def test_verification_routes_are_registered() -> None:
    routes = {route.path for route in app.routes}
    assert "/api/v1/incidents/{incident_id}/verification" in routes
    assert "/api/v1/incidents/{incident_id}/verifications" in routes
    assert "/api/v1/verifications/evaluate-due" in routes
    assert "/api/v1/verifications/{run_id}" in routes
