from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.domain.enums import IncidentStatus
from app.main import app
from app.models import ComponentRecord, IncidentRecord, MachineRecord


@pytest.fixture
def api_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    engine = create_database_engine(
        Settings(
            environment="test",
            database_url=f"sqlite:///{tmp_path / 'api-layer.db'}",
            sqlite_wal_enabled=False,
        )
    )
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

    def override_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db
    old_llm = getattr(app.state, "llm_provider", None)
    old_semantic = getattr(app.state, "semantic_history_service", None)
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "factory": factory,
                "machine_id": machine_id,
                "component_id": component_id,
            }
    finally:
        app.dependency_overrides.clear()
        if old_llm is None and hasattr(app.state, "llm_provider"):
            delattr(app.state, "llm_provider")
        else:
            app.state.llm_provider = old_llm
        if old_semantic is None and hasattr(app.state, "semantic_history_service"):
            delattr(app.state, "semantic_history_service")
        else:
            app.state.semantic_history_service = old_semantic
        engine.dispose()


def _machine_event(env: dict[str, Any], record_id: str = "api-event-1") -> dict[str, Any]:
    return {
        "machine_id": str(env["machine_id"]),
        "component_id": str(env["component_id"]),
        "original_source_record_id": record_id,
        "original_timestamp": "2026-10-02T14:30:00Z",
        "event_type": "HYDRAULIC_PRESSURE_WARNING",
        "payload": {"pressure": 17},
        "raw_payload": {"fault_code": "H17", "reading": 17},
        "provenance": {"source_system": "edge-gateway-7"},
    }


def _incident_id(env: dict[str, Any]) -> UUID:
    with env["factory"]() as session:
        return session.scalars(select(IncidentRecord.id)).one()


def test_assets_ingestion_idempotency_timeline_and_incident_journey(api_env: dict[str, Any]) -> None:
    client = api_env["client"]

    machine = client.get(f"/api/v1/machines/{api_env['machine_id']}")
    components = client.get(f"/api/v1/machines/{api_env['machine_id']}/components")
    component = client.get(f"/api/v1/components/{api_env['component_id']}")
    assert machine.status_code == components.status_code == component.status_code == 200
    assert components.json()["components"][0]["id"] == str(api_env["component_id"])

    body = _machine_event(api_env)
    first = client.post("/api/v1/evidence/machine-events", json=body)
    replay = client.post("/api/v1/evidence/machine-events", json=body)
    assert first.status_code == replay.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["evidence_id"] == first.json()["evidence_id"]

    timeline = client.get(f"/api/v1/machines/{api_env['machine_id']}/timeline")
    assert timeline.status_code == 200
    assert [item["evidence_id"] for item in timeline.json()["evidence"]] == [first.json()["evidence_id"]]

    incident = client.get(f"/api/v1/incidents/{_incident_id(api_env)}")
    assert incident.status_code == 200
    assert incident.json()["status"] == "OPEN"


def test_verification_handover_and_audit_journey(api_env: dict[str, Any]) -> None:
    client = api_env["client"]
    client.post("/api/v1/evidence/machine-events", json=_machine_event(api_env))
    incident_id = _incident_id(api_env)

    started = client.post(f"/api/v1/incidents/{incident_id}/verification")
    assert started.status_code == 201
    assert client.get(f"/api/v1/incidents/{incident_id}").json()["status"] == "VERIFYING"

    handover = client.post("/api/v1/handovers")
    assert handover.status_code == 201
    packet_id = handover.json()["id"]
    assert any(item["incident_id"] == str(incident_id) for item in handover.json()["items"])

    acknowledged = client.post(f"/api/v1/handovers/{packet_id}/acknowledge")
    assert acknowledged.status_code == 200
    # Acknowledgement is audit/state metadata only; it never verifies/closes.
    assert client.get(f"/api/v1/incidents/{incident_id}").json()["status"] == "VERIFYING"

    audit = client.get(f"/api/v1/incidents/{incident_id}/audit")
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["audit_events"]]
    assert "HANDOVER_ACKNOWLEDGED" in actions


def test_evidence_bundle_and_ai_are_read_only_from_incident_state(api_env: dict[str, Any]) -> None:
    client = api_env["client"]
    client.post("/api/v1/evidence/machine-events", json=_machine_event(api_env))
    incident_id = _incident_id(api_env)

    before = client.get(f"/api/v1/incidents/{incident_id}").json()
    bundle = client.get(f"/api/v1/incidents/{incident_id}/evidence-bundle")
    ai = client.post(f"/api/v1/incidents/{incident_id}/ai-analysis")
    after = client.get(f"/api/v1/incidents/{incident_id}").json()

    assert bundle.status_code == 200
    assert bundle.json()["primary_incident_evidence"]
    assert ai.status_code == 200
    assert ai.json()["result_type"] == "FALLBACK"  # AI disabled by default
    assert before == after


def test_structured_not_found_validation_and_conflict_errors(api_env: dict[str, Any]) -> None:
    client = api_env["client"]

    missing = client.get(f"/api/v1/incidents/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "INCIDENT_NOT_FOUND"

    invalid = client.post("/api/v1/evidence/machine-events", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(invalid.json()["error"]["details"], list)

    client.post("/api/v1/evidence/machine-events", json=_machine_event(api_env))
    packet = client.post("/api/v1/handovers").json()
    assert client.post(f"/api/v1/handovers/{packet['id']}/acknowledge").status_code == 200
    conflict = client.post(f"/api/v1/handovers/{packet['id']}/acknowledge")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "HANDOVER_ALREADY_ACKNOWLEDGED"


def test_protected_history_and_evidence_have_no_delete_routes() -> None:
    protected_fragments = (
        "/evidence",
        "/audit",
        "/timeline",
        "/verifications",
        "/verification",
        "/handovers",
    )
    destructive = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if "DELETE" not in route.methods:
            continue
        if any(fragment in route.path for fragment in protected_fragments):
            destructive.append(route.path)
    assert destructive == []


def test_openapi_tags_and_versioned_route_groups_present() -> None:
    schema = app.openapi()
    tags = {tag["name"] for tag in schema["tags"]}
    assert {
        "Machines",
        "Components",
        "Evidence",
        "Timeline",
        "Incidents",
        "Verification",
        "Handover",
        "Evidence Bundle",
        "AI Insights",
    } <= tags

    paths = set(schema["paths"])
    assert "/api/v1/machines/{machine_id}" in paths
    assert "/api/v1/components/{component_id}" in paths
    assert "/api/v1/evidence/machine-events" in paths
    assert "/api/v1/incidents/{incident_id}/evidence-bundle" in paths
    assert "/api/v1/incidents/{incident_id}/ai-analysis" in paths
