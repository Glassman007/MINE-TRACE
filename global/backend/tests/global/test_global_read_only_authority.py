from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_v1_router
from app.db.base import Base
from app.db.session import get_db_session
from app.domain.enums import IncidentStatus, VerificationRunResult
from app.models import IncidentRecord, MachineRecord, VerificationRunRecord


def _client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    app = FastAPI()
    app.include_router(api_v1_router)

    def db_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = db_override
    return TestClient(app), factory, engine


def test_global_router_exposes_no_local_authority_mutation_routes() -> None:
    app = FastAPI()
    app.include_router(api_v1_router)
    paths_and_methods = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    forbidden = {
        ("/api/v1/incidents/{incident_id}/evidence/{evidence_id}/move", "POST"),
        ("/api/v1/incidents/{incident_id}/split", "POST"),
        ("/api/v1/incidents/{incident_id}/verification", "POST"),
        ("/api/v1/verifications/evaluate-due", "POST"),
        ("/api/v1/handover", "POST"),
        ("/api/v1/handover/{packet_id}/acknowledge", "POST"),
        ("/api/v1/evidence", "POST"),
        ("/api/v1/evidence/events", "POST"),
        ("/api/v1/ingestion/machine-event", "POST"),
        ("/api/v1/ingestion/maintenance-record", "POST"),
        ("/api/v1/ingestion/human-observation", "POST"),
    }
    assert paths_and_methods.isdisjoint(forbidden)


def test_only_expected_post_routes_remain() -> None:
    app = FastAPI()
    app.include_router(api_v1_router)
    post_paths = {
        route.path
        for route in app.routes
        if "POST" in getattr(route, "methods", set())
    }
    assert post_paths == {
        "/api/v1/sync/packages",
        "/api/v1/incidents/{incident_id}/ai-analysis",
        "/api/v1/search/semantic",
        "/api/v1/ai/analyze",
    }


def test_synchronized_verification_remains_readable_without_mutation() -> None:
    client, factory, engine = _client()
    machine_id = uuid4()
    incident_id = uuid4()
    run_id = uuid4()
    with factory() as session:
        session.add(MachineRecord(id=machine_id, asset_code="G-1"))
        session.flush()
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.VERIFIED))
        session.add(
            VerificationRunRecord(
                id=run_id,
                incident_id=incident_id,
                source_machine_id=machine_id,
                rule_identifier="edge.rule.v1",
                result=VerificationRunResult.SUCCEEDED,
                started_at=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
                outcome_payload={"source": "edge"},
            )
        )
        session.commit()
    try:
        response = client.get(f"/api/v1/incidents/{incident_id}/verifications")
        assert response.status_code == 200
        payload = response.json()
        assert payload["runs"][0]["id"] == str(run_id)
        assert payload["runs"][0]["result"] == "SUCCEEDED"
        assert client.post(f"/api/v1/incidents/{incident_id}/verification").status_code in {404, 405}
        assert client.post("/api/v1/verifications/evaluate-due").status_code in {404, 405}
    finally:
        client.close()
        engine.dispose()
