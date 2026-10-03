from __future__ import annotations

from collections.abc import Generator
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
from app.domain.enums import SyncOutboxState
from app.integrations.sync import SyncTransportUnavailableError
from app.main import app
from app.models import (
    MachineRecord,
    MachineSessionReportRecord,
    OperatingSessionRecord,
    SyncConflictRecord,
    SyncOutboxItemRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.sync import SyncAcknowledgement, SyncAcknowledgementStatus
from app.services.sync import SyncOutboxService


class FakeTransport:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior
        self.calls: list[dict[str, Any]] = []

    def send(self, envelope):
        self.calls.append(envelope.model_dump(mode="json", exclude_none=True))
        if self.behavior == "timeout":
            raise SyncTransportUnavailableError("simulated timeout")
        if self.behavior == "malformed":
            return {"schema_version": "1.0", "package_id": str(envelope.package_id)}
        if self.behavior == "unsupported":
            # Deliberately include invalid business fields. The service must reject
            # the unsupported major before interpreting them.
            return {"schema_version": "2.0", "business": "must-not-be-guessed"}
        status = {
            "success": SyncAcknowledgementStatus.ACKNOWLEDGED,
            "duplicate": SyncAcknowledgementStatus.DUPLICATE,
            "conflict": SyncAcknowledgementStatus.CONFLICT,
        }[self.behavior]
        return SyncAcknowledgement(
            schema_version="1.0",
            package_id=envelope.package_id,
            status=status,
            central_revision=(99 if status == SyncAcknowledgementStatus.CONFLICT else 2),
            acknowledged_at=envelope.created_at,
            message="revision mismatch" if status == SyncAcknowledgementStatus.CONFLICT else None,
        )


class SequenceTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(self, envelope):
        self.calls.append(envelope.model_dump(mode="json", exclude_none=True))
        if len(self.calls) == 1:
            raise SyncTransportUnavailableError("first attempt timeout")
        return SyncAcknowledgement(
            schema_version="1.0",
            package_id=envelope.package_id,
            status=SyncAcknowledgementStatus.ACKNOWLEDGED,
            central_revision=2,
            acknowledged_at=envelope.created_at,
        )


@pytest.fixture
def sync_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    database_path = tmp_path / "sync.db"
    machine_id = uuid4()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path}",
        sqlite_wal_enabled=False,
        local_machine_id=machine_id,
        local_node_id="edge-test-node",
        transport_schema_version="1.0",
        sync_retry_max_attempts=5,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))

    def override_get_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            opened = client.post(
                "/api/v1/sessions", json={"started_at": "2026-10-03T08:00:00Z"}
            )
            assert opened.status_code == 201, opened.text
            session_id = UUID(opened.json()["session_id"])
            closed = client.post(
                f"/api/v1/sessions/{session_id}/close",
                json={"ended_at": "2026-10-03T12:00:00Z", "operating_hours": 3.5},
            )
            assert closed.status_code == 200, closed.text
            with factory() as db:
                outbox = db.scalar(select(SyncOutboxItemRecord))
                assert outbox is not None
                item_id = outbox.id
                original_payload = outbox.payload_json
                package_id = outbox.package_id
            yield {
                "client": client,
                "factory": factory,
                "settings": settings,
                "session_id": session_id,
                "item_id": item_id,
                "package_id": package_id,
                "original_payload": original_payload,
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _service(env: dict[str, Any], transport) -> SyncOutboxService:
    return SyncOutboxService(
        lambda: SQLAlchemyUnitOfWork(env["factory"]),
        env["settings"],
        transport=transport,
    )


def test_session_close_durably_queues_exact_envelope(sync_env: dict[str, Any]) -> None:
    with sync_env["factory"]() as session:
        rows = session.scalars(select(SyncOutboxItemRecord)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.state == SyncOutboxState.PENDING
        assert row.attempt_count == 0
        assert row.payload_json["package_id"] == str(row.package_id)
        assert row.payload_json["session_id"] == str(sync_env["session_id"])
        assert row.payload_json["machine_session_report"]["report_id"] == str(row.report_id)
        assert row.payload_json["evidence_manifest"]["schema_version"] == "1.0"
        assert row.payload_json["policy_selected_raw_evidence"] == []


def test_outbox_survives_service_restart(sync_env: dict[str, Any]) -> None:
    # A new UoW/service instance against the same file sees the queued row.
    transport = FakeTransport("success")
    restarted = _service(sync_env, transport)
    result = restarted.send_item(sync_env["item_id"])
    assert result.state == SyncOutboxState.ACKNOWLEDGED
    assert len(transport.calls) == 1


def test_success_persists_acknowledgement(sync_env: dict[str, Any]) -> None:
    transport = FakeTransport("success")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    with sync_env["factory"]() as session:
        row = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert row is not None
        assert row.state == SyncOutboxState.ACKNOWLEDGED
        assert row.acknowledged_at is not None
        assert row.central_revision == 2
        assert row.transport_available is True
        assert row.last_error is None


def test_timeout_marks_failed_without_damaging_canonical_state(sync_env: dict[str, Any]) -> None:
    transport = FakeTransport("timeout")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    with sync_env["factory"]() as session:
        outbox = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert outbox is not None
        assert outbox.state == SyncOutboxState.FAILED
        assert outbox.transport_available is False
        assert "timeout" in (outbox.last_error or "")
        assert session.get(OperatingSessionRecord, sync_env["session_id"]) is not None
        assert session.scalar(
            select(MachineSessionReportRecord).where(
                MachineSessionReportRecord.session_id == sync_env["session_id"]
            )
        ) is not None


def test_retry_reuses_exact_package_revision_and_payload(sync_env: dict[str, Any]) -> None:
    transport = SequenceTransport()
    service = _service(sync_env, transport)
    first = service.send_item(sync_env["item_id"])
    assert first.state == SyncOutboxState.FAILED
    second = service.send_item(sync_env["item_id"])
    assert second.state == SyncOutboxState.ACKNOWLEDGED
    assert len(transport.calls) == 2
    assert transport.calls[0] == transport.calls[1] == sync_env["original_payload"]
    assert transport.calls[0]["package_id"] == str(sync_env["package_id"])
    assert transport.calls[0]["local_revision"] == transport.calls[1]["local_revision"]


def test_duplicate_acknowledgement_is_idempotent_success(sync_env: dict[str, Any]) -> None:
    transport = FakeTransport("duplicate")
    service = _service(sync_env, transport)
    result = service.send_item(sync_env["item_id"])
    assert result.state == SyncOutboxState.ACKNOWLEDGED
    # A locally acknowledged package is not transmitted again.
    again = service.send_item(sync_env["item_id"])
    assert again.state == SyncOutboxState.ACKNOWLEDGED
    assert len(transport.calls) == 1


def test_revision_conflict_is_persisted_without_overwrite(sync_env: dict[str, Any]) -> None:
    transport = FakeTransport("conflict")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    with sync_env["factory"]() as session:
        outbox = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        conflicts = session.scalars(select(SyncConflictRecord)).all()
        assert outbox is not None
        assert outbox.state == SyncOutboxState.CONFLICT
        assert outbox.local_revision == 2
        assert outbox.central_revision == 99
        assert len(conflicts) == 1
        assert conflicts[0].local_revision == 2
        assert conflicts[0].central_revision == 99
        assert conflicts[0].object_id == outbox.report_id


def test_malformed_acknowledgement_fails_closed(sync_env: dict[str, Any]) -> None:
    transport = FakeTransport("malformed")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    with sync_env["factory"]() as session:
        row = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert row is not None
        assert row.state == SyncOutboxState.FAILED
        assert row.transport_available is True
        assert "malformed" in (row.last_error or "").lower()


def test_unsupported_ack_schema_major_is_rejected_before_business_fields(
    sync_env: dict[str, Any],
) -> None:
    transport = FakeTransport("unsupported")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    with sync_env["factory"]() as session:
        row = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert row is not None
        assert row.state == SyncOutboxState.FAILED
        assert row.transport_available is True
        assert "unsupported transport schema major" in (row.last_error or "")


def test_payload_checksum_is_verified_before_transport(sync_env: dict[str, Any]) -> None:
    with sync_env["factory"].begin() as session:
        row = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert row is not None
        tampered = dict(row.payload_json)
        tampered["report_revision"] = 77
        row.payload_json = tampered
    transport = FakeTransport("success")
    _service(sync_env, transport).send_item(sync_env["item_id"])
    assert transport.calls == []
    with sync_env["factory"]() as session:
        row = session.get(SyncOutboxItemRecord, sync_env["item_id"])
        assert row is not None
        assert row.state == SyncOutboxState.FAILED
        assert "checksum" in (row.last_error or "").lower() or "invalid" in (
            row.last_error or ""
        ).lower()


def test_sync_status_reports_persisted_backend_facts_only(sync_env: dict[str, Any]) -> None:
    response = sync_env["client"].get("/api/v1/sync/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["machine_id"] == str(sync_env["settings"].local_machine_id)
    assert body["pending_item_count"] == 1
    assert body["failed_item_count"] == 0
    assert body["conflict_count"] == 0
    assert body["latest_package"]["state"] == "PENDING"
    assert body["latest_package"]["package_id"] == str(sync_env["package_id"])
    assert body["transport_configured"] is False
    assert "transport_available" not in body
    assert "last_acknowledgement" not in body
    assert "last_transmission_attempt" not in body


def test_configured_global_url_does_not_imply_connectivity_or_acknowledgement(
    sync_env: dict[str, Any],
) -> None:
    sync_env["settings"].global_backend_base_url = "https://central.example.test"
    response = sync_env["client"].get("/api/v1/sync/status")
    assert response.status_code == 200
    body = response.json()
    assert body["transport_configured"] is True
    assert "transport_available" not in body
    assert body["latest_package"]["state"] == "PENDING"
    assert "last_acknowledgement" not in body


def test_sync_status_survives_restart_and_reports_degraded_network(
    sync_env: dict[str, Any],
) -> None:
    transport = FakeTransport("timeout")
    # New service instance simulates restart; its failure state is persisted.
    _service(sync_env, transport).send_item(sync_env["item_id"])
    response = sync_env["client"].get("/api/v1/sync/status")
    assert response.status_code == 200
    body = response.json()
    assert body["pending_item_count"] == 0
    assert body["failed_item_count"] == 1
    assert body["latest_package"]["state"] == "FAILED"
    assert body["latest_package"]["attempt_count"] == 1
    assert body["transport_available"] is False
    assert body["transport_checked_at"]
    assert body["last_transmission_attempt"]
    assert "timeout" in body["last_error"]
    assert "last_acknowledgement" not in body


def test_sync_status_exposes_revision_conflict_summary(sync_env: dict[str, Any]) -> None:
    _service(sync_env, FakeTransport("conflict")).send_item(sync_env["item_id"])
    response = sync_env["client"].get("/api/v1/sync/status")
    assert response.status_code == 200
    body = response.json()
    assert body["conflict_count"] == 1
    assert body["latest_package"]["state"] == "CONFLICT"
    assert body["conflicts"] == [
        {
            "conflict_id": body["conflicts"][0]["conflict_id"],
            "package_id": str(sync_env["package_id"]),
            "object_id": body["conflicts"][0]["object_id"],
            "local_revision": 2,
            "central_revision": 99,
            "detected_at": body["conflicts"][0]["detected_at"],
            "state": "OPEN",
            "resolution_metadata": {},
        }
    ]
