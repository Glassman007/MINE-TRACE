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

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.main import app
from app.models import (
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceAttachmentRecord,
    EvidenceEventRecord,
    ImmutableContextSnapshotViolation,
    MachineRecord,
)


@pytest.fixture
def timeline_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    engine = create_database_engine(
        Settings(
            environment="test",
            database_url=f"sqlite:///{tmp_path / 'timeline.db'}",
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
    component_a = uuid4()
    component_b = uuid4()
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add_all(
            [
                ComponentRecord(id=component_a, machine_id=machine_id),
                ComponentRecord(id=component_b, machine_id=machine_id),
            ]
        )

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
                "component_a": component_a,
                "component_b": component_b,
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _event(
    *,
    evidence_id: UUID,
    machine_id: UUID,
    component_id: UUID | None,
    source_record_id: str,
    original: datetime,
    ingested: datetime,
) -> EvidenceEventRecord:
    return EvidenceEventRecord(
        id=evidence_id,
        machine_id=machine_id,
        component_id=component_id,
        source_type="MACHINE_EVENT",
        original_source_record_id=source_record_id,
        original_timestamp=original,
        ingestion_timestamp=ingested,
        canonical_event_type="TEST_EVENT",
        canonical_payload={"record": source_record_id},
        raw_source_payload={"raw": source_record_id},
        provenance={"source_system": "test-gateway"},
    )


def _fixed_context() -> dict[str, Any]:
    return {
        "shift": {"value": "A", "quality": "KNOWN", "freshness_basis": "shift-roster"},
        "location": {"value": "level-4", "quality": "KNOWN", "freshness_basis": "location-sample"},
        "machine_operating_state": {"value": "RUNNING", "quality": "KNOWN", "freshness_basis": "ecu-event"},
        "workload": {"value": 0.82, "quality": "STALE", "freshness_basis": "load-sample-5m-prior"},
        "environment": {"value": None, "quality": "UNKNOWN", "freshness_basis": "not-reported"},
    }


def test_timeline_orders_by_original_timestamp_not_ingestion_timestamp(
    timeline_env: dict[str, Any],
) -> None:
    first_id = uuid4()
    second_id = uuid4()
    with timeline_env["factory"].begin() as session:
        # Deliberately reverse ingestion order relative to event-time order.
        session.add_all(
            [
                _event(
                    evidence_id=first_id,
                    machine_id=timeline_env["machine_id"],
                    component_id=timeline_env["component_a"],
                    source_record_id="first-original",
                    original=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
                    ingested=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
                ),
                _event(
                    evidence_id=second_id,
                    machine_id=timeline_env["machine_id"],
                    component_id=timeline_env["component_a"],
                    source_record_id="second-original",
                    original=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                    ingested=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
                ),
            ]
        )

    response = timeline_env["client"].get(
        f"/api/v1/machines/{timeline_env['machine_id']}/timeline"
    )
    assert response.status_code == 200
    assert [item["evidence_id"] for item in response.json()["evidence"]] == [
        str(first_id),
        str(second_id),
    ]


def test_timeline_filters_by_component_and_timestamp_range(
    timeline_env: dict[str, Any],
) -> None:
    kept = uuid4()
    with timeline_env["factory"].begin() as session:
        session.add_all(
            [
                _event(
                    evidence_id=uuid4(), machine_id=timeline_env["machine_id"],
                    component_id=timeline_env["component_a"], source_record_id="too-early",
                    original=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
                    ingested=datetime(2026, 10, 2, 8, 1, tzinfo=timezone.utc),
                ),
                _event(
                    evidence_id=kept, machine_id=timeline_env["machine_id"],
                    component_id=timeline_env["component_a"], source_record_id="kept",
                    original=datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc),
                    ingested=datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc),
                ),
                _event(
                    evidence_id=uuid4(), machine_id=timeline_env["machine_id"],
                    component_id=timeline_env["component_b"], source_record_id="other-component",
                    original=datetime(2026, 10, 2, 9, 45, tzinfo=timezone.utc),
                    ingested=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                ),
            ]
        )

    response = timeline_env["client"].get(
        f"/api/v1/machines/{timeline_env['machine_id']}/timeline",
        params={
            "component_id": str(timeline_env["component_a"]),
            "from": "2026-10-02T09:00:00Z",
            "to": "2026-10-02T10:00:00Z",
        },
    )
    assert response.status_code == 200
    assert [item["evidence_id"] for item in response.json()["evidence"]] == [str(kept)]


def test_context_snapshot_is_fixed_historical_and_immutable(
    timeline_env: dict[str, Any],
) -> None:
    body = {
        "machine_id": str(timeline_env["machine_id"]),
        "component_id": str(timeline_env["component_a"]),
        "original_source_record_id": "context-001",
        "original_timestamp": "2026-10-02T09:15:00Z",
        "event_type": "PRESSURE_WARNING",
        "payload": {"pressure": 17},
        "raw_payload": {"pressure_raw": 17},
        "provenance": {"source_system": "edge-1"},
        "context_snapshot": _fixed_context(),
    }
    ingested = timeline_env["client"].post("/api/v1/evidence/machine-events", json=body)
    assert ingested.status_code == 200
    evidence_id = UUID(ingested.json()["evidence_id"])

    timeline = timeline_env["client"].get(
        f"/api/v1/machines/{timeline_env['machine_id']}/timeline"
    )
    assert timeline.status_code == 200
    context = timeline.json()["evidence"][0]["context_snapshots"][0]["context"]
    assert set(context) == {
        "shift", "location", "machine_operating_state", "workload", "environment"
    }
    assert context["workload"]["quality"] == "STALE"
    assert context["workload"]["freshness_basis"] == "load-sample-5m-prior"

    with timeline_env["factory"]() as session:
        snapshot = session.scalar(
            select(ContextSnapshotRecord).where(
                ContextSnapshotRecord.evidence_event_id == evidence_id
            )
        )
        assert snapshot is not None
        snapshot.snapshot_payload = _fixed_context() | {
            "shift": {"value": "CURRENT", "quality": "KNOWN", "freshness_basis": "current-state"}
        }
        with pytest.raises(ImmutableContextSnapshotViolation):
            session.commit()
        session.rollback()


def test_attachment_metadata_and_checksum_persist_and_audio_is_metadata_only(
    timeline_env: dict[str, Any],
) -> None:
    body = {
        "machine_id": str(timeline_env["machine_id"]),
        "component_id": None,
        "original_source_record_id": "audio-001",
        "original_timestamp": "2026-10-02T10:00:00Z",
        "observation_type": "OPERATOR_AUDIO_OBSERVATION",
        "payload": {"note": "audio captured"},
        "raw_payload": {"device": "handheld-2"},
        "provenance": {"source_system": "operator-terminal"},
        "attachments": [
            {
                "attachment_type": "AUDIO",
                "storage_reference": "local://evidence/audio-001.wav",
                "mime_type": "audio/wav",
                "file_size": 2048,
                "checksum": "sha256:abc123",
                "created_at": "2026-10-02T10:00:03Z",
            }
        ],
    }
    response = timeline_env["client"].post(
        "/api/v1/evidence/human-observations", json=body
    )
    assert response.status_code == 200
    evidence_id = UUID(response.json()["evidence_id"])

    with timeline_env["factory"]() as session:
        attachment = session.scalar(
            select(EvidenceAttachmentRecord).where(
                EvidenceAttachmentRecord.evidence_event_id == evidence_id
            )
        )
        assert attachment is not None
        assert attachment.attachment_type == "AUDIO"
        assert attachment.storage_reference == "local://evidence/audio-001.wav"
        assert attachment.mime_type == "audio/wav"
        assert attachment.file_size == 2048
        assert attachment.checksum == "sha256:abc123"

    timeline = timeline_env["client"].get(
        f"/api/v1/machines/{timeline_env['machine_id']}/timeline"
    )
    item = timeline.json()["evidence"][0]
    assert item["attachments"][0]["checksum"] == "sha256:abc123"
    assert "transcript" not in item["attachments"][0]


def test_missing_optional_attachments_do_not_break_evidence(
    timeline_env: dict[str, Any],
) -> None:
    body = {
        "machine_id": str(timeline_env["machine_id"]),
        "component_id": None,
        "original_source_record_id": "no-attachment-001",
        "original_timestamp": "2026-10-02T11:00:00Z",
        "record_type": "INSPECTION",
        "payload": {"result": "ok"},
        "raw_payload": {"result": "ok"},
        "provenance": {"source_system": "cmms"},
    }
    response = timeline_env["client"].post(
        "/api/v1/evidence/maintenance-records", json=body
    )
    assert response.status_code == 200

    timeline = timeline_env["client"].get(
        f"/api/v1/machines/{timeline_env['machine_id']}/timeline"
    )
    assert timeline.status_code == 200
    assert timeline.json()["evidence"][0]["attachments"] == []
