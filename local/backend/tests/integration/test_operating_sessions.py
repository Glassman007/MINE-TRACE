from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.main import app
from app.models import (
    ComponentRecord,
    EvidenceEventRecord,
    IncidentEvidenceLinkRecord,
    MachineRecord,
    MachineSessionReportRecord,
    OperatingSessionRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.sessions import OperatingSessionService


@pytest.fixture
def local_session_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    database_path = tmp_path / "local-session.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path}",
        sqlite_wal_enabled=False,
        local_machine_id=uuid4(),
        transport_schema_version="1.0",
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    component_id = uuid4()
    other_machine_id = uuid4()
    other_component_id = uuid4()
    with factory.begin() as session:
        session.add_all(
            [
                MachineRecord(id=settings.local_machine_id),
                MachineRecord(id=other_machine_id),
            ]
        )
        session.flush()
        session.add_all(
            [
                ComponentRecord(id=component_id, machine_id=settings.local_machine_id),
                ComponentRecord(id=other_component_id, machine_id=other_machine_id),
            ]
        )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def override_settings() -> Settings:
        return settings

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = override_settings
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "factory": factory,
                "settings": settings,
                "database_path": database_path,
                "component_id": component_id,
                "other_machine_id": other_machine_id,
                "other_component_id": other_component_id,
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _open(client: TestClient, started_at: str = "2026-10-03T08:00:00Z") -> dict[str, Any]:
    response = client.post("/api/v1/sessions", json={"started_at": started_at})
    assert response.status_code == 201, response.text
    return response.json()


def _machine_event(
    *,
    machine_id: UUID,
    component_id: UUID,
    session_id: UUID | None,
    record_id: str,
    timestamp: str,
    event_type: str = "HYDRAULIC_PRESSURE_WARNING",
    raw_payload: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "machine_id": str(machine_id),
        "component_id": str(component_id),
        "session_id": str(session_id) if session_id is not None else None,
        "original_source_record_id": record_id,
        "original_timestamp": timestamp,
        "event_type": event_type,
        "payload": {"value": 17, "unit": "bar"},
        "raw_payload": raw_payload or {"raw_samples": [17, 18, 16]},
        "provenance": {"source_system": "edge-gateway", "record": record_id},
        "attachments": attachments or [],
    }


def _maintenance_record(
    *,
    machine_id: UUID,
    component_id: UUID,
    session_id: UUID,
    record_id: str,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "machine_id": str(machine_id),
        "component_id": str(component_id),
        "session_id": str(session_id),
        "original_source_record_id": record_id,
        "original_timestamp": timestamp,
        "record_type": "FILTER_REPLACEMENT",
        "payload": {"work_order": "WO-17", "action": "filter replaced"},
        "raw_payload": {"technician_note": "filter replaced and torqued"},
        "provenance": {"source_system": "maintenance-log", "work_order": "WO-17"},
    }


def test_session_open_read_active_close_and_persistence(local_session_env: dict[str, Any]) -> None:
    client = local_session_env["client"]
    opened = _open(client)
    session_id = UUID(opened["session_id"])

    assert opened["machine_id"] == str(local_session_env["settings"].local_machine_id)
    assert opened["state"] == "OPEN"
    assert opened["operating_hours"] is None
    assert opened["revision"] == 1

    active = client.get("/api/v1/sessions/active")
    read = client.get(f"/api/v1/sessions/{session_id}")
    assert active.status_code == read.status_code == 200
    assert active.json()["session_id"] == read.json()["session_id"] == str(session_id)

    closed = client.post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T12:00:00Z", "operating_hours": 3.5},
    )
    assert closed.status_code == 200
    assert closed.json()["state"] == "CLOSED"
    assert closed.json()["operating_hours"] == 3.5
    assert closed.json()["revision"] == 2

    with local_session_env["factory"]() as session:
        persisted = session.get(OperatingSessionRecord, session_id)
        assert persisted is not None
        assert persisted.state.value == "CLOSED"
        assert persisted.operating_hours == 3.5
        assert session.scalar(
            select(MachineSessionReportRecord).where(
                MachineSessionReportRecord.session_id == session_id
            )
        ) is not None


def test_session_survives_repository_restart(local_session_env: dict[str, Any]) -> None:
    opened = _open(local_session_env["client"])
    session_id = UUID(opened["session_id"])

    # A brand-new SQLAlchemy session/UoW reads the persisted row; no in-memory
    # service state participates in session identity.
    service = OperatingSessionService(
        lambda: SQLAlchemyUnitOfWork(local_session_env["factory"]),
        local_session_env["settings"],
    )
    restarted_view = service.get_session(session_id)
    assert restarted_view.session_id == session_id
    assert restarted_view.state.value == "OPEN"


def test_only_one_active_session_is_allowed(local_session_env: dict[str, Any]) -> None:
    _open(local_session_env["client"])
    duplicate = local_session_env["client"].post(
        "/api/v1/sessions",
        json={"started_at": "2026-10-03T08:05:00Z"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "OPERATING_SESSION_CONFLICT"


def test_close_does_not_infer_operating_hours_from_elapsed_time(
    local_session_env: dict[str, Any],
) -> None:
    opened = _open(local_session_env["client"], "2026-10-03T08:00:00Z")
    response = local_session_env["client"].post(
        f"/api/v1/sessions/{opened['session_id']}/close",
        json={"ended_at": "2026-10-03T16:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["operating_hours"] is None


def test_invalid_operating_hours_and_time_order_are_rejected(
    local_session_env: dict[str, Any],
) -> None:
    opened = _open(local_session_env["client"])
    negative = local_session_env["client"].post(
        f"/api/v1/sessions/{opened['session_id']}/close",
        json={"ended_at": "2026-10-03T09:00:00Z", "operating_hours": -0.1},
    )
    assert negative.status_code == 422

    backwards = local_session_env["client"].post(
        f"/api/v1/sessions/{opened['session_id']}/close",
        json={"ended_at": "2026-10-03T07:59:59Z", "operating_hours": 0.1},
    )
    assert backwards.status_code == 409


def test_rollover_closes_current_generates_report_and_opens_new(
    local_session_env: dict[str, Any],
) -> None:
    first = _open(local_session_env["client"])
    rollover = local_session_env["client"].post(
        "/api/v1/sessions/rollover",
        json={
            "ended_at": "2026-10-03T12:00:00Z",
            "new_started_at": "2026-10-03T12:00:00Z",
            "operating_hours": 4,
        },
    )
    assert rollover.status_code == 200, rollover.text
    body = rollover.json()
    assert body["closed_session"]["session_id"] == first["session_id"]
    assert body["closed_session"]["state"] == "CLOSED"
    assert body["new_session"]["state"] == "OPEN"
    assert body["new_session"]["session_id"] != first["session_id"]

    report = local_session_env["client"].get(
        f"/api/v1/sessions/{first['session_id']}/report"
    )
    assert report.status_code == 200
    assert report.json()["session_id"] == first["session_id"]


def test_explicit_evidence_session_association_is_persisted(
    local_session_env: dict[str, Any],
) -> None:
    opened = _open(local_session_env["client"])
    session_id = UUID(opened["session_id"])
    body = _machine_event(
        machine_id=local_session_env["settings"].local_machine_id,
        component_id=local_session_env["component_id"],
        session_id=session_id,
        record_id="session-evidence-1",
        timestamp="2026-10-03T08:15:00Z",
    )
    response = local_session_env["client"].post(
        "/api/v1/evidence/machine-events", json=body
    )
    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == str(session_id)

    with local_session_env["factory"]() as session:
        evidence = session.get(EvidenceEventRecord, UUID(response.json()["evidence_id"]))
        assert evidence is not None
        assert evidence.session_id == session_id


def test_evidence_without_session_is_not_attached_by_timestamp_guessing(
    local_session_env: dict[str, Any],
) -> None:
    _open(local_session_env["client"], "2026-10-03T08:00:00Z")
    body = _machine_event(
        machine_id=local_session_env["settings"].local_machine_id,
        component_id=local_session_env["component_id"],
        session_id=None,
        record_id="unknown-session-history",
        timestamp="2026-10-03T08:30:00Z",
    )
    response = local_session_env["client"].post(
        "/api/v1/evidence/machine-events", json=body
    )
    assert response.status_code == 200
    assert response.json()["session_id"] is None
    with local_session_env["factory"]() as session:
        evidence = session.get(EvidenceEventRecord, UUID(response.json()["evidence_id"]))
        assert evidence is not None
        assert evidence.session_id is None


def test_closed_session_rejects_new_evidence_association(
    local_session_env: dict[str, Any],
) -> None:
    opened = _open(local_session_env["client"])
    local_session_env["client"].post(
        f"/api/v1/sessions/{opened['session_id']}/close",
        json={"ended_at": "2026-10-03T09:00:00Z"},
    )
    body = _machine_event(
        machine_id=local_session_env["settings"].local_machine_id,
        component_id=local_session_env["component_id"],
        session_id=UUID(opened["session_id"]),
        record_id="late-closed-session-evidence",
        timestamp="2026-10-03T08:45:00Z",
    )
    response = local_session_env["client"].post(
        "/api/v1/evidence/machine-events", json=body
    )
    assert response.status_code == 409


def test_configured_machine_isolation_rejects_other_machine_evidence(
    local_session_env: dict[str, Any],
) -> None:
    body = _machine_event(
        machine_id=local_session_env["other_machine_id"],
        component_id=local_session_env["other_component_id"],
        session_id=None,
        record_id="other-machine",
        timestamp="2026-10-03T08:10:00Z",
    )
    response = local_session_env["client"].post(
        "/api/v1/evidence/machine-events", json=body
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCAL_NODE_CONFLICT"




def test_configured_machine_cannot_read_another_machine_session(
    local_session_env: dict[str, Any],
) -> None:
    foreign_session_id = uuid4()
    with local_session_env["factory"].begin() as session:
        session.add(
            OperatingSessionRecord(
                session_id=foreign_session_id,
                machine_id=local_session_env["other_machine_id"],
                started_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                state="OPEN",
                revision=1,
                created_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
            )
        )

    response = local_session_env["client"].get(f"/api/v1/sessions/{foreign_session_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OPERATING_SESSION_NOT_FOUND"


def test_incident_can_span_multiple_operating_sessions(local_session_env: dict[str, Any]) -> None:
    client = local_session_env["client"]
    machine_id = local_session_env["settings"].local_machine_id
    component_id = local_session_env["component_id"]

    first = _open(client, "2026-10-03T08:00:00Z")
    evidence_one = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=UUID(first["session_id"]),
            record_id="span-1",
            timestamp="2026-10-03T08:10:00Z",
        ),
    )
    assert evidence_one.status_code == 200
    client.post(
        f"/api/v1/sessions/{first['session_id']}/close",
        json={"ended_at": "2026-10-03T08:20:00Z"},
    )

    second = _open(client, "2026-10-03T08:20:00Z")
    evidence_two = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=UUID(second["session_id"]),
            record_id="span-2",
            timestamp="2026-10-03T08:30:00Z",
        ),
    )
    assert evidence_two.status_code == 200

    with local_session_env["factory"]() as session:
        ids = [UUID(evidence_one.json()["evidence_id"]), UUID(evidence_two.json()["evidence_id"])]
        records = [session.get(EvidenceEventRecord, evidence_id) for evidence_id in ids]
        assert records[0] is not None and records[1] is not None
        assert records[0].session_id != records[1].session_id
        incident_ids = []
        for evidence_id in ids:
            links = session.scalars(
                select(IncidentEvidenceLinkRecord).where(
                    IncidentEvidenceLinkRecord.evidence_event_id == evidence_id,
                    IncidentEvidenceLinkRecord.is_active.is_(True),
                )
            ).all()
            assert len(links) == 1
            incident_ids.append(links[0].incident_id)
        assert incident_ids[0] == incident_ids[1]


def _active_incident_id(factory: sessionmaker[Session], evidence_id: UUID) -> UUID:
    with factory() as session:
        link = session.scalar(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.evidence_event_id == evidence_id,
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
        )
        assert link is not None
        return link.incident_id


def test_session_report_is_stable_across_repeated_retrieval(
    local_session_env: dict[str, Any],
) -> None:
    client = local_session_env["client"]
    opened = _open(client)
    session_id = UUID(opened["session_id"])
    evidence = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=local_session_env["settings"].local_machine_id,
            component_id=local_session_env["component_id"],
            session_id=session_id,
            record_id="deterministic-report-evidence",
            timestamp="2026-10-03T08:10:00Z",
        ),
    )
    assert evidence.status_code == 200
    close = client.post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T10:00:00Z", "operating_hours": 1.75},
    )
    assert close.status_code == 200

    first = client.get(f"/api/v1/sessions/{session_id}/report")
    second = client.get(f"/api/v1/sessions/{session_id}/report")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.json() == second.json()
    assert first.json()["report_id"] == second.json()["report_id"]
    assert first.json()["generated_at"] == second.json()["generated_at"]
    assert first.json()["checksum"] == second.json()["checksum"]


def test_report_manifest_reuses_attachment_metadata_and_excludes_raw_payload(
    local_session_env: dict[str, Any],
) -> None:
    client = local_session_env["client"]
    opened = _open(client)
    session_id = UUID(opened["session_id"])
    raw_payload = {
        "high_frequency_samples": [100, 101, 99, 102],
        "raw_private_marker": "must-not-be-in-manifest",
    }
    body = _machine_event(
        machine_id=local_session_env["settings"].local_machine_id,
        component_id=local_session_env["component_id"],
        session_id=session_id,
        record_id="manifest-attachment",
        timestamp="2026-10-03T08:15:00Z",
        raw_payload=raw_payload,
        attachments=[
            {
                "attachment_type": "VIBRATION_CAPTURE",
                "storage_reference": "local://evidence/vibration-001.bin",
                "mime_type": "application/octet-stream",
                "file_size": 4096,
                "checksum": "sha256:attachment-checksum-001",
                "created_at": "2026-10-03T08:15:01Z",
            }
        ],
    )
    response = client.post("/api/v1/evidence/machine-events", json=body)
    assert response.status_code == 200, response.text
    client.post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T09:00:00Z"},
    )

    report = client.get(f"/api/v1/sessions/{session_id}/report")
    assert report.status_code == 200
    payload = report.json()
    entries = payload["evidence_manifest"]["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["evidence_id"] == response.json()["evidence_id"]
    assert entry["machine_id"] == str(local_session_env["settings"].local_machine_id)
    assert entry["session_id"] == str(session_id)
    assert entry["component_id"] == str(local_session_env["component_id"])
    assert entry["incident_id"] == str(
        _active_incident_id(local_session_env["factory"], UUID(response.json()["evidence_id"]))
    )
    assert entry["source_type"] == "MACHINE_EVENT"
    assert entry["original_timestamp"] == "2026-10-03T08:15:00Z"
    assert entry["provenance_reference"] == "source-record:MACHINE_EVENT:manifest-attachment"
    assert entry["checksum"].startswith("sha256:")
    assert entry["checksum_scope"] == "CANONICAL_EVIDENCE_RECORD"
    assert entry["storage_references"] == [
        {
            "attachment_id": entry["storage_references"][0]["attachment_id"],
            "storage_reference": "local://evidence/vibration-001.bin",
            "checksum": "sha256:attachment-checksum-001",
            "mime_type": "application/octet-stream",
            "file_size": 4096,
        }
    ]
    serialized = report.text
    assert "raw_private_marker" not in serialized
    assert "high_frequency_samples" not in serialized


def test_report_contains_maintenance_verification_and_unresolved_work_from_canonical_state(
    local_session_env: dict[str, Any],
) -> None:
    client = local_session_env["client"]
    machine_id = local_session_env["settings"].local_machine_id
    component_id = local_session_env["component_id"]
    opened = _open(client)
    session_id = UUID(opened["session_id"])

    fault = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=session_id,
            record_id="report-fault",
            timestamp="2026-10-03T08:05:00Z",
        ),
    )
    assert fault.status_code == 200
    fault_id = UUID(fault.json()["evidence_id"])
    incident_id = _active_incident_id(local_session_env["factory"], fault_id)

    maintenance = client.post(
        "/api/v1/evidence/maintenance-records",
        json=_maintenance_record(
            machine_id=machine_id,
            component_id=component_id,
            session_id=session_id,
            record_id="report-maintenance",
            timestamp="2026-10-03T08:20:00Z",
        ),
    )
    assert maintenance.status_code == 200

    verification = client.post(f"/api/v1/incidents/{incident_id}/verification")
    assert verification.status_code == 201, verification.text

    close = client.post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T08:30:00Z", "operating_hours": 0.4},
    )
    assert close.status_code == 200
    report = client.get(f"/api/v1/sessions/{session_id}/report").json()

    incident_summary = next(
        item for item in report["incident_summaries"] if item["incident_id"] == str(incident_id)
    )
    assert incident_summary["component_id"] == str(component_id)
    assert incident_summary["state"] == "VERIFYING"
    assert incident_summary["occurrence_count"] == 1
    assert incident_summary["first_seen"] == incident_summary["last_seen"]

    assert any(
        action["evidence_id"] == maintenance.json()["evidence_id"]
        and action["action_type"] == "FILTER_REPLACEMENT"
        for action in report["maintenance_actions"]
    )
    assert any(
        item["verification_run_id"] == verification.json()["id"]
        and item["incident_id"] == str(incident_id)
        for item in report["verification_results"]
    )
    assert any(
        item["incident_id"] == str(incident_id) and item["state"] == "VERIFYING"
        for item in report["unresolved_work"]
    )
    assert report["sync_metadata"] == {
        "local_revision": 2,
        "report_revision": 1,
        "acknowledgement_state": "NOT_ACKNOWLEDGED",
    }


def test_closed_report_is_not_rewritten_when_incident_later_recurs_in_new_session(
    local_session_env: dict[str, Any],
) -> None:
    client = local_session_env["client"]
    machine_id = local_session_env["settings"].local_machine_id
    component_id = local_session_env["component_id"]

    first = _open(client, "2026-10-03T08:00:00Z")
    first_event = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=UUID(first["session_id"]),
            record_id="immutable-1",
            timestamp="2026-10-03T08:05:00Z",
        ),
    )
    assert first_event.status_code == 200
    client.post(
        f"/api/v1/sessions/{first['session_id']}/close",
        json={"ended_at": "2026-10-03T08:10:00Z"},
    )
    before = client.get(f"/api/v1/sessions/{first['session_id']}/report")
    assert before.status_code == 200

    second = _open(client, "2026-10-03T08:10:00Z")
    recurrence = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=UUID(second["session_id"]),
            record_id="immutable-2",
            timestamp="2026-10-03T08:15:00Z",
        ),
    )
    assert recurrence.status_code == 200

    after = client.get(f"/api/v1/sessions/{first['session_id']}/report")
    assert after.status_code == 200
    assert after.content == before.content




def test_session_report_carries_forward_unresolved_machine_work_without_timestamp_inference(
    local_session_env: dict[str, Any],
) -> None:
    client = local_session_env["client"]
    machine_id = local_session_env["settings"].local_machine_id
    component_id = local_session_env["component_id"]

    legacy_like = client.post(
        "/api/v1/evidence/machine-events",
        json=_machine_event(
            machine_id=machine_id,
            component_id=component_id,
            session_id=None,
            record_id="carry-forward-unresolved",
            timestamp="2026-10-03T07:30:00Z",
        ),
    )
    assert legacy_like.status_code == 200
    evidence_id = UUID(legacy_like.json()["evidence_id"])
    incident_id = _active_incident_id(local_session_env["factory"], evidence_id)

    opened = _open(client, "2026-10-03T08:00:00Z")
    session_id = opened["session_id"]
    close = client.post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T09:00:00Z"},
    )
    assert close.status_code == 200

    report = client.get(f"/api/v1/sessions/{session_id}/report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["evidence_manifest"]["entries"] == []
    assert any(
        item["incident_id"] == str(incident_id) and item["state"] == "OPEN"
        for item in payload["unresolved_work"]
    )
    assert any(
        item["incident_id"] == str(incident_id)
        for item in payload["incident_summaries"]
    )


def test_report_generated_at_is_session_close_time_not_mutable_wall_clock(
    local_session_env: dict[str, Any],
) -> None:
    opened = _open(local_session_env["client"])
    session_id = opened["session_id"]
    local_session_env["client"].post(
        f"/api/v1/sessions/{session_id}/close",
        json={"ended_at": "2026-10-03T11:45:00Z"},
    )
    report = local_session_env["client"].get(
        f"/api/v1/sessions/{session_id}/report"
    ).json()
    assert report["generated_at"] == "2026-10-03T11:45:00Z"
    assert report["operating_summary"]["end"] == "2026-10-03T11:45:00Z"
