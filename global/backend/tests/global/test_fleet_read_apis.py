from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.health import router as health_router
from app.api.router import api_v1_router
from app.db.base import Base
from app.db.session import get_db_session
from app.domain.enums import IncidentStatus, VerificationRunResult
from app.models import (
    ComponentRecord,
    EvidenceEventRecord,
    IncidentRecord,
    MachineRecord,
    MaintenanceActionRecord,
    OperatingSessionRecord,
    SyncConflictRecord,
    SyncReceiptRecord,
    VerificationRunRecord,
)

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api_v1_router)
    app.include_router(health_router)

    def db_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = db_override
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def _seed(factory):
    machine_a, machine_b, machine_c = uuid4(), uuid4(), uuid4()
    component_a, component_b = uuid4(), uuid4()
    session_old, session_new, session_b = uuid4(), uuid4(), uuid4()
    incident_open, incident_verified, incident_b = uuid4(), uuid4(), uuid4()
    with factory() as db:
        db.add_all([
            MachineRecord(id=machine_a, display_name="A", asset_code="A-1", machine_type="HAUL_TRUCK", model="MT-100", site_name="North"),
            MachineRecord(id=machine_b, display_name="B", asset_code="B-1", machine_type="EXCAVATOR", model="EX-9", site_name="South"),
            MachineRecord(id=machine_c, display_name="C", asset_code="C-1", machine_type="HAUL_TRUCK", model="MT-200", site_name="North"),
        ])
        db.flush()
        db.add_all([
            ComponentRecord(id=component_a, machine_id=machine_a, display_name="Pump", component_type="PUMP"),
            ComponentRecord(id=component_b, machine_id=machine_b, display_name="Brake", component_type="BRAKE"),
        ])
        db.add_all([
            OperatingSessionRecord(id=session_old, machine_id=machine_a, started_at=NOW - timedelta(days=2), ended_at=NOW - timedelta(days=2, hours=-8), state="CLOSED", latest_report_revision=1),
            OperatingSessionRecord(id=session_new, machine_id=machine_a, started_at=NOW - timedelta(hours=8), ended_at=NOW, state="CLOSED", latest_report_revision=2),
            OperatingSessionRecord(id=session_b, machine_id=machine_b, started_at=NOW - timedelta(hours=7), ended_at=NOW, state="CLOSED", latest_report_revision=1),
        ])
        db.add_all([
            IncidentRecord(id=incident_open, machine_id=machine_a, component_id=component_a, status=IncidentStatus.OPEN, due_state="DUE", due_time=NOW + timedelta(hours=2), first_seen_at=NOW - timedelta(hours=6), last_seen_at=NOW - timedelta(hours=1)),
            IncidentRecord(id=incident_verified, machine_id=machine_a, component_id=component_a, status=IncidentStatus.VERIFIED, first_seen_at=NOW - timedelta(days=2), last_seen_at=NOW - timedelta(days=2)),
            IncidentRecord(id=incident_b, machine_id=machine_b, component_id=component_b, status=IncidentStatus.VERIFYING, first_seen_at=NOW - timedelta(hours=5), last_seen_at=NOW - timedelta(minutes=30)),
        ])
        db.add(MaintenanceActionRecord(id=uuid4(), machine_id=machine_a, incident_id=incident_open, session_id=session_new, component_id=component_a, action_type="INSPECTION", description="Checked pump", original_timestamp=NOW - timedelta(minutes=45), provenance={"source": "edge"}))
        db.add(VerificationRunRecord(id=uuid4(), incident_id=incident_b, session_id=session_b, source_machine_id=machine_b, rule_identifier="edge.rule", result=None, started_at=NOW - timedelta(hours=1), outcome_payload={}))
        evidence_id = uuid4()
        db.add(EvidenceEventRecord(id=evidence_id, source_machine_id=machine_a, machine_id=machine_a, session_id=session_new, component_id=component_a, source_type="HUMAN_OBSERVATION", original_source_record_id="obs-1", original_timestamp=NOW - timedelta(hours=2), canonical_event_type="OPERATOR_NOTE", canonical_payload={"text":"pump noise"}, raw_source_payload={}, provenance={}))
        receipt_a = SyncReceiptRecord(id=uuid4(), package_id=uuid4(), source_machine_id=machine_a, session_id=session_new, report_revision=2, schema_version="1.0.0", checksum="sha256:" + "a"*64, acknowledgement_status="ACCEPTED", received_at=NOW - timedelta(minutes=10), acknowledged_at=NOW - timedelta(minutes=9))
        receipt_b = SyncReceiptRecord(id=uuid4(), package_id=uuid4(), source_machine_id=machine_b, session_id=session_b, report_revision=1, schema_version="1.0.0", checksum="sha256:" + "b"*64, acknowledgement_status="ACCEPTED", received_at=NOW - timedelta(hours=3), acknowledged_at=NOW - timedelta(hours=3))
        db.add_all([receipt_a, receipt_b])
        db.flush()
        db.add(SyncConflictRecord(id=uuid4(), source_machine_id=machine_b, session_id=session_b, incoming_package_id=uuid4(), existing_receipt_id=receipt_b.id, conflict_type="SAME_REVISION_CONTENT_MISMATCH", incoming_report_revision=1, existing_report_revision=1, incoming_checksum="sha256:" + "c"*64, existing_checksum=receipt_b.checksum, incoming_metadata={"incoming":"x"}, existing_metadata={"existing":"y"}, resolution_status="UNRESOLVED"))
        db.commit()
    return {
        "machine_a": machine_a, "machine_b": machine_b, "machine_c": machine_c,
        "component_a": component_a, "component_b": component_b,
        "session_old": session_old, "session_new": session_new,
        "incident_open": incident_open, "incident_verified": incident_verified, "incident_b": incident_b,
    }


def test_required_health_and_empty_fleet(api) -> None:
    client, _ = api
    assert client.get("/health").status_code == 200
    response = client.get("/api/v1/fleet/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["fleet_machine_count"] == 0
    assert body["recent_sessions"] == []
    assert body["unresolved_incident_count"] == 0


def test_machine_filters_pagination_and_sync_recency(api) -> None:
    client, factory = api
    ids = _seed(factory)
    north = client.get("/api/v1/machines", params={"site":"North", "model":"MT-100"}).json()
    assert north["total"] == 1
    assert north["items"][0]["id"] == str(ids["machine_a"])
    assert north["items"][0]["latest_sync_received_at"] is not None
    page = client.get("/api/v1/machines", params={"offset":1, "limit":1}).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_sessions_are_newest_first(api) -> None:
    client, factory = api
    ids = _seed(factory)
    payload = client.get(f"/api/v1/machines/{ids['machine_a']}/sessions").json()
    assert [item["session_id"] for item in payload["items"]] == [str(ids["session_new"]), str(ids["session_old"])]


def test_incident_exact_filters_cover_machine_component_time_status_model_site(api) -> None:
    client, factory = api
    ids = _seed(factory)
    params = {
        "machine": str(ids["machine_a"]),
        "component": str(ids["component_a"]),
        "status": "OPEN",
        "model": "MT-100",
        "site": "North",
        "start": (NOW - timedelta(hours=2)).isoformat(),
        "end": NOW.isoformat(),
    }
    payload = client.get("/api/v1/incidents", params=params).json()
    assert payload["total"] == 1
    assert payload["items"][0]["incident_id"] == str(ids["incident_open"])
    assert payload["items"][0]["site_name"] == "North"
    by_machine = client.get(f"/api/v1/machines/{ids['machine_b']}/incidents").json()
    assert by_machine["total"] == 1


def test_maintenance_queue_is_canonical_and_deterministically_ordered(api) -> None:
    client, factory = api
    ids = _seed(factory)
    payload = client.get("/api/v1/maintenance-queue").json()
    assert payload["total"] == 2
    assert payload["items"][0]["incident_id"] == str(ids["incident_open"])
    assert payload["items"][0]["latest_maintenance_action_type"] == "INSPECTION"
    assert "priority" not in payload["items"][0]
    verifying = next(item for item in payload["items"] if item["incident_id"] == str(ids["incident_b"]))
    assert verifying["verification_required"] is True


def test_sync_health_separates_canonical_from_optional_capabilities_and_conflicts(api) -> None:
    client, factory = api
    ids = _seed(factory)
    payload = client.get("/api/v1/sync/health", params={"stale_after_hours":2}).json()
    assert payload["canonical_database"] == "ok"
    assert payload["semantic"]["status"] == "UNAVAILABLE"
    assert payload["embeddings"]["status"] == "UNAVAILABLE"
    assert payload["ai"]["status"] == "DISABLED"
    by_machine = {item["machine_id"]: item for item in payload["machines"]}
    assert by_machine[str(ids["machine_b"])]["stale"] is True
    assert by_machine[str(ids["machine_a"])]["stale"] is False
    conflicts = client.get("/api/v1/sync/conflicts", params={"unresolved_only":True}).json()
    assert conflicts["total"] == 1
    assert conflicts["items"][0]["incoming_metadata"] == {"incoming":"x"}
    assert conflicts["items"][0]["existing_metadata"] == {"existing":"y"}


def test_relational_analytics_work_without_qdrant(api) -> None:
    client, factory = api
    _seed(factory)
    summary = client.get("/api/v1/analytics/summary").json()
    assert summary["machines"] == 3
    assert summary["incidents"] == 3
    assert summary["unresolved_incidents"] == 2
    assert summary["evidence"] == 1
    assert summary["maintenance_actions"] == 1
    sites = client.get("/api/v1/analytics/incidents/by-site").json()
    assert {item["key"]:item["count"] for item in sites["items"]} == {"North":2, "South":1}
    trend = client.get("/api/v1/analytics/incidents/trend").json()
    assert sum(item["count"] for item in trend["items"]) == 3


def test_incident_maintenance_history_is_read_only_and_complete(api) -> None:
    client, factory = api
    ids = _seed(factory)
    payload = client.get(f"/api/v1/incidents/{ids['incident_open']}/maintenance-actions").json()
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["action_type"] == "INSPECTION"
    assert payload["actions"][0]["incident_id"] == str(ids["incident_open"])
    assert client.post(f"/api/v1/incidents/{ids['incident_open']}/maintenance-actions").status_code == 405
