from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.domain.enums import IncidentAuditAction, IncidentStatus
from app.main import app
from app.models import (
    HandoverItemRecord,
    HandoverPacketRecord,
    ImmutableHandoverItemViolation,
    IncidentAuditEventRecord,
    IncidentRecord,
    MachineRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.handover import HandoverAlreadyAcknowledgedError, HandoverService


@pytest.fixture
def handover_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    from app.core.settings import Settings

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'handover.db'}",
        sqlite_wal_enabled=False,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        yield {
            "engine": engine,
            "factory": factory,
            "service": HandoverService(lambda: SQLAlchemyUnitOfWork(factory)),
            "client": TestClient(app),
        }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _seed_incident(
    factory: sessionmaker[Session],
    *,
    machine_id: UUID,
    status: IncidentStatus,
    owner_ref: str | None,
    severity: str | None,
    due_state: str | None,
    due_time: datetime | None,
) -> UUID:
    incident_id = uuid4()
    with factory.begin() as session:
        session.add(
            IncidentRecord(
                id=incident_id,
                machine_id=machine_id,
                status=status,
                owner_ref=owner_ref,
                severity=severity,
                due_state=due_state,
                due_time=due_time,
            )
        )
    return incident_id


def _seed_machine(factory: sessionmaker[Session]) -> UUID:
    machine_id = uuid4()
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
    return machine_id


def test_all_required_audit_actions_remain_controlled_enum_values() -> None:
    assert {action.value for action in IncidentAuditAction} == {
        "INCIDENT_CREATED",
        "EVIDENCE_LINKED",
        "EVIDENCE_UNLINKED",
        "INCIDENT_SPLIT",
        "STATUS_CHANGED",
        "OWNER_CHANGED",
        "SEVERITY_CHANGED",
        "DUE_STATE_CHANGED",
        "DUE_TIME_CHANGED",
        "RECURRENCE_RECORDED",
        "HANDOVER_ACKNOWLEDGED",
    }


def test_incident_audit_endpoint_returns_append_only_history(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    incident_id = _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.OPEN,
        owner_ref=None,
        severity="S2",
        due_state=None,
        due_time=None,
    )
    occurred_at = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)
    audit_id = uuid4()
    with factory.begin() as session:
        session.add(
            IncidentAuditEventRecord(
                id=audit_id,
                incident_id=incident_id,
                action=IncidentAuditAction.INCIDENT_CREATED,
                occurred_at=occurred_at,
                payload={"source": "test"},
            )
        )

    with handover_env["client"] as client:
        response = client.get(f"/api/v1/incidents/{incident_id}/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == str(incident_id)
    assert body["audit_events"] == [
        {
            "id": str(audit_id),
            "action": "INCIDENT_CREATED",
            "occurred_at": "2026-10-02T18:00:00Z",
            "payload": {"source": "test"},
        }
    ]


def test_handover_contains_only_open_verifying_and_recurred_incidents(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    expected: set[UUID] = set()
    for status in (IncidentStatus.OPEN, IncidentStatus.VERIFYING, IncidentStatus.RECURRED):
        expected.add(
            _seed_incident(
                factory,
                machine_id=machine_id,
                status=status,
                owner_ref=f"owner-{status.value}",
                severity="S2",
                due_state="DUE",
                due_time=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
            )
        )
    verified_id = _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.VERIFIED,
        owner_ref="verified-owner",
        severity="S1",
        due_state=None,
        due_time=None,
    )

    packet = handover_env["service"].create_handover(
        created_at=datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc)
    )

    actual = {item.incident_id for item in packet.items}
    assert actual == expected
    assert verified_id not in actual


def test_handover_item_is_historical_snapshot_after_incident_changes(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    old_due_time = datetime(2026, 10, 3, 9, 30, tzinfo=timezone.utc)
    incident_id = _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.OPEN,
        owner_ref="owner-a",
        severity="HIGH",
        due_state="DUE_SOON",
        due_time=old_due_time,
    )
    packet = handover_env["service"].create_handover(
        created_at=datetime(2026, 10, 2, 19, 30, tzinfo=timezone.utc)
    )

    with factory.begin() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        incident.status = IncidentStatus.VERIFYING
        incident.owner_ref = "owner-b"
        incident.severity = "LOW"
        incident.due_state = "NOT_DUE"
        incident.due_time = old_due_time + timedelta(days=2)

    reread = handover_env["service"].get_handover(packet.id)
    assert len(reread.items) == 1
    snapshot = reread.items[0]
    assert snapshot.incident_id == incident_id
    assert snapshot.status == IncidentStatus.OPEN
    assert snapshot.owner_ref == "owner-a"
    assert snapshot.severity == "HIGH"
    assert snapshot.due_state == "DUE_SOON"
    assert snapshot.due_time == old_due_time


def test_handover_snapshot_rows_reject_normal_orm_updates(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.OPEN,
        owner_ref="owner-a",
        severity="HIGH",
        due_state=None,
        due_time=None,
    )
    packet = handover_env["service"].create_handover()

    with factory() as session:
        item = session.scalar(
            select(HandoverItemRecord).where(
                HandoverItemRecord.handover_packet_id == packet.id
            )
        )
        assert item is not None
        item.severity_snapshot = "REWRITTEN"
        with pytest.raises(ImmutableHandoverItemViolation):
            session.commit()
        session.rollback()


def test_acknowledgement_records_packet_and_audits_without_changing_status(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    incident_ids: dict[UUID, IncidentStatus] = {}
    for status in (IncidentStatus.OPEN, IncidentStatus.VERIFYING, IncidentStatus.RECURRED):
        incident_id = _seed_incident(
            factory,
            machine_id=machine_id,
            status=status,
            owner_ref=None,
            severity=None,
            due_state=None,
            due_time=None,
        )
        incident_ids[incident_id] = status

    packet = handover_env["service"].create_handover(
        created_at=datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)
    )
    ack_time = datetime(2026, 10, 2, 20, 5, tzinfo=timezone.utc)
    acknowledged = handover_env["service"].acknowledge(
        packet.id, acknowledged_at=ack_time
    )

    assert acknowledged.acknowledged_at == ack_time
    with factory() as session:
        persisted_packet = session.get(HandoverPacketRecord, packet.id)
        assert persisted_packet is not None
        assert persisted_packet.acknowledged_at is not None
        for incident_id, original_status in incident_ids.items():
            incident = session.get(IncidentRecord, incident_id)
            assert incident is not None
            assert incident.status == original_status
            audits = session.scalars(
                select(IncidentAuditEventRecord).where(
                    IncidentAuditEventRecord.incident_id == incident_id,
                    IncidentAuditEventRecord.action
                    == IncidentAuditAction.HANDOVER_ACKNOWLEDGED,
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].payload == {"handover_packet_id": str(packet.id)}


def test_acknowledgement_is_not_reapplied(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.OPEN,
        owner_ref=None,
        severity=None,
        due_state=None,
        due_time=None,
    )
    packet = handover_env["service"].create_handover()
    handover_env["service"].acknowledge(packet.id)

    with pytest.raises(HandoverAlreadyAcknowledgedError):
        handover_env["service"].acknowledge(packet.id)


def test_handover_api_create_get_and_acknowledge(
    handover_env: dict[str, Any],
) -> None:
    factory = handover_env["factory"]
    machine_id = _seed_machine(factory)
    incident_id = _seed_incident(
        factory,
        machine_id=machine_id,
        status=IncidentStatus.OPEN,
        owner_ref="shift-owner",
        severity="S2",
        due_state="DUE",
        due_time=datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc),
    )

    with handover_env["client"] as client:
        created = client.post("/api/v1/handovers")
        assert created.status_code == 201
        packet_id = created.json()["id"]
        assert created.json()["items"][0]["incident_id"] == str(incident_id)

        fetched = client.get(f"/api/v1/handovers/{packet_id}")
        assert fetched.status_code == 200
        assert fetched.json()["items"][0]["owner_ref"] == "shift-owner"

        acknowledged = client.post(f"/api/v1/handovers/{packet_id}/acknowledge")
        assert acknowledged.status_code == 200
        assert acknowledged.json()["acknowledged_at"] is not None

        refetched = client.get(f"/api/v1/handovers/{packet_id}")
        assert refetched.status_code == 200
        assert refetched.json()["items"][0]["status"] == "OPEN"

    with factory() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        assert incident.status == IncidentStatus.OPEN
