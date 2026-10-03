from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.domain.enums import ContextQuality, EvidenceSourceType
from app.main import app
from app.models import (
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceEventRecord,
    MachineRecord,
)
from app.repositories.sqlalchemy import SQLAlchemyContextSnapshotRepository
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.ingestion import MachineEventInput
from app.services.ingestion import IngestionService


@pytest.fixture
def ingestion_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    engine = create_database_engine(
        Settings(
            environment="test",
            database_url=f"sqlite:///{tmp_path / 'ingestion.db'}",
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

    def override_get_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
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
        engine.dispose()


def _common_payload(machine_id: UUID, component_id: UUID | None, record_id: str) -> dict[str, Any]:
    return {
        "machine_id": str(machine_id),
        "component_id": str(component_id) if component_id is not None else None,
        "original_source_record_id": record_id,
        "original_timestamp": "2026-10-02T14:30:00Z",
        "payload": {"value": 17, "unit": "bar"},
        "raw_payload": {"fault_code": "H17", "reading": 17},
        "provenance": {"source_system": "edge-gateway-7", "file": "shift-a.json"},
    }


def _count(factory: sessionmaker[Session], record_type: type[Any]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(record_type)) or 0


def test_valid_machine_event(ingestion_env: dict[str, Any]) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], ingestion_env["component_id"], "machine-001"
    )
    body["event_type"] = "HYDRAULIC_PRESSURE_WARNING"
    body["context_snapshot"] = {
        "shift": {"value": "A", "quality": "KNOWN", "freshness_basis": "operator-shift-record"},
        "location": {"value": "level-4", "quality": "KNOWN", "freshness_basis": "machine-location-event"},
        "machine_operating_state": {"value": "RUNNING", "quality": "KNOWN", "freshness_basis": "ecu-event"},
        "workload": {"value": 0.75, "quality": "STALE", "freshness_basis": "last-load-sample"},
        "environment": {"value": None, "quality": "UNKNOWN", "freshness_basis": "not-reported"},
    }

    response = ingestion_env["client"].post("/api/v1/evidence/machine-events", json=body)

    assert response.status_code == 200
    evidence_id = UUID(response.json()["evidence_id"])
    with ingestion_env["factory"]() as session:
        record = session.get(EvidenceEventRecord, evidence_id)
        assert record is not None
        assert record.source_type == EvidenceSourceType.MACHINE_EVENT.value
        assert record.canonical_event_type == "HYDRAULIC_PRESSURE_WARNING"
        snapshots = session.scalars(
            select(ContextSnapshotRecord).where(
                ContextSnapshotRecord.evidence_event_id == evidence_id
            )
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].quality is None
        assert snapshots[0].snapshot_payload["shift"]["quality"] == "KNOWN"


def test_valid_maintenance_record(ingestion_env: dict[str, Any]) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], ingestion_env["component_id"], "maintenance-001"
    )
    body["record_type"] = "PUMP_REPLACEMENT"

    response = ingestion_env["client"].post(
        "/api/v1/evidence/maintenance-records", json=body
    )

    assert response.status_code == 200
    evidence_id = UUID(response.json()["evidence_id"])
    with ingestion_env["factory"]() as session:
        record = session.get(EvidenceEventRecord, evidence_id)
        assert record is not None
        assert record.source_type == EvidenceSourceType.MAINTENANCE_RECORD.value
        assert record.canonical_event_type == "PUMP_REPLACEMENT"


def test_valid_human_observation(ingestion_env: dict[str, Any]) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], None, "observation-001"
    )
    body["observation_type"] = "UNUSUAL_GRINDING_NOISE"

    response = ingestion_env["client"].post(
        "/api/v1/evidence/human-observations", json=body
    )

    assert response.status_code == 200
    evidence_id = UUID(response.json()["evidence_id"])
    with ingestion_env["factory"]() as session:
        record = session.get(EvidenceEventRecord, evidence_id)
        assert record is not None
        assert record.source_type == EvidenceSourceType.HUMAN_OBSERVATION.value
        assert record.component_id is None


def test_unknown_machine_rejected(ingestion_env: dict[str, Any]) -> None:
    body = _common_payload(uuid4(), None, "machine-unknown")
    body["event_type"] = "FAULT"

    response = ingestion_env["client"].post("/api/v1/evidence/machine-events", json=body)

    assert response.status_code == 404
    assert "unknown machine" in response.json()["detail"]
    assert _count(ingestion_env["factory"], EvidenceEventRecord) == 0


def test_unknown_component_rejected(ingestion_env: dict[str, Any]) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], uuid4(), "component-unknown"
    )
    body["record_type"] = "INSPECTION"

    response = ingestion_env["client"].post(
        "/api/v1/evidence/maintenance-records", json=body
    )

    assert response.status_code == 404
    assert "unknown component" in response.json()["detail"]
    assert _count(ingestion_env["factory"], EvidenceEventRecord) == 0


def test_duplicate_replay_returns_same_evidence_and_creates_no_extra_rows(
    ingestion_env: dict[str, Any],
) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], ingestion_env["component_id"], "replay-001"
    )
    body["event_type"] = "BRAKE_TEMPERATURE_WARNING"
    body["context_snapshot"] = {
        "shift": {"value": "B", "quality": "KNOWN", "freshness_basis": "operator-shift-record"},
        "location": {"value": None, "quality": "UNKNOWN", "freshness_basis": "not-reported"},
        "machine_operating_state": {"value": "RUNNING", "quality": "KNOWN", "freshness_basis": "ecu-event"},
        "workload": {"value": None, "quality": "UNKNOWN", "freshness_basis": "not-reported"},
        "environment": {"value": None, "quality": "UNKNOWN", "freshness_basis": "not-reported"},
    }

    first = ingestion_env["client"].post("/api/v1/evidence/machine-events", json=body)
    second = ingestion_env["client"].post("/api/v1/evidence/machine-events", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["evidence_id"] == second.json()["evidence_id"]
    assert _count(ingestion_env["factory"], EvidenceEventRecord) == 1
    assert _count(ingestion_env["factory"], ContextSnapshotRecord) == 1


def test_raw_payload_original_timestamp_and_provenance_are_preserved(
    ingestion_env: dict[str, Any],
) -> None:
    body = _common_payload(
        ingestion_env["machine_id"], ingestion_env["component_id"], "preserve-001"
    )
    body["observation_type"] = "OPERATOR_NOTE"
    body["raw_payload"] = {
        "note": "Grinding noise near pump",
        "operator_sequence": 42,
        "nested": {"original": True},
    }
    body["provenance"] = {
        "source_system": "operator-terminal-3",
        "operator_ref": "shift-user-19",
        "source_file": "observations.ndjson",
    }
    body["original_timestamp"] = "2026-10-02T09:15:27Z"

    response = ingestion_env["client"].post(
        "/api/v1/evidence/human-observations", json=body
    )
    assert response.status_code == 200

    evidence_id = UUID(response.json()["evidence_id"])
    with ingestion_env["factory"]() as session:
        record = session.get(EvidenceEventRecord, evidence_id)
        assert record is not None
        assert record.raw_source_payload == body["raw_payload"]
        assert record.provenance == body["provenance"]
        # SQLite drops timezone metadata for DATETIME, but the original UTC wall
        # time used for authoritative historical ordering is unchanged.
        assert record.original_timestamp == datetime(2026, 10, 2, 9, 15, 27)


def test_evidence_and_context_rollback_together_on_failure(
    ingestion_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = ingestion_env["factory"]
    machine_id = ingestion_env["machine_id"]
    component_id = ingestion_env["component_id"]

    request = MachineEventInput(
        machine_id=machine_id,
        component_id=component_id,
        original_source_record_id="rollback-001",
        original_timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        event_type="ROLLBACK_TEST",
        payload={"value": 1},
        raw_payload={"raw": 1},
        provenance={"source_system": "test"},
        context_snapshot={
            "shift": {"value": "A", "quality": "KNOWN", "freshness_basis": "test"},
            "location": {"value": None, "quality": "UNKNOWN", "freshness_basis": "test"},
            "machine_operating_state": {"value": None, "quality": "UNKNOWN", "freshness_basis": "test"},
            "workload": {"value": None, "quality": "UNKNOWN", "freshness_basis": "test"},
            "environment": {"value": None, "quality": "UNKNOWN", "freshness_basis": "test"},
        },
    )
    service = IngestionService(lambda: SQLAlchemyUnitOfWork(factory))

    def fail_context_add(self: SQLAlchemyContextSnapshotRepository, record: ContextSnapshotRecord) -> None:
        raise RuntimeError("forced context persistence failure")

    monkeypatch.setattr(SQLAlchemyContextSnapshotRepository, "add", fail_context_add)

    with pytest.raises(RuntimeError, match="forced context persistence failure"):
        service.ingest_machine_event(request)

    assert _count(factory, EvidenceEventRecord) == 0
    assert _count(factory, ContextSnapshotRecord) == 0
