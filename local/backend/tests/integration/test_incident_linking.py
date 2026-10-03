from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
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
from app.domain.enums import IncidentAuditAction, IncidentStatus
from app.main import app
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


@pytest.fixture
def linking_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'incident-linking.db'}",
        sqlite_wal_enabled=False,
        incident_linking_window_minutes=60,
        incident_linking_rule_identifier="test.rule.v1",
        incident_linking_rule_name="Test deterministic linking rule",
        incident_linking_compatible_event_pairs={
            "HYDRAULIC_PRESSURE_WARNING": ("HYDRAULIC_PRESSURE_LOW",),
        },
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_a = uuid4()
    machine_b = uuid4()
    component_a1 = uuid4()
    component_a2 = uuid4()
    component_b1 = uuid4()
    with factory.begin() as session:
        session.add_all([MachineRecord(id=machine_a), MachineRecord(id=machine_b)])
        session.flush()
        session.add_all(
            [
                ComponentRecord(id=component_a1, machine_id=machine_a),
                ComponentRecord(id=component_a2, machine_id=machine_a),
                ComponentRecord(id=component_b1, machine_id=machine_b),
            ]
        )

    linker = IncidentLinkingService(settings)
    ingestion = IngestionService(
        lambda: SQLAlchemyUnitOfWork(factory),
        incident_linking_service=linker,
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
                "settings": settings,
                "factory": factory,
                "linker": linker,
                "ingestion": ingestion,
                "client": client,
                "machine_a": machine_a,
                "machine_b": machine_b,
                "component_a1": component_a1,
                "component_a2": component_a2,
                "component_b1": component_b1,
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _request(
    *,
    machine_id: UUID,
    component_id: UUID | None,
    record_id: str,
    at: datetime,
    event_type: str,
) -> MachineEventInput:
    return MachineEventInput(
        machine_id=machine_id,
        component_id=component_id,
        original_source_record_id=record_id,
        original_timestamp=at,
        event_type=event_type,
        payload={"event_type": event_type},
        raw_payload={"event_type": event_type, "record_id": record_id},
        provenance={"source_system": "incident-linking-test"},
    )


def _incident_ids_for_evidence(factory: sessionmaker[Session], evidence_id: UUID) -> list[UUID]:
    with factory() as session:
        return list(
            session.scalars(
                select(IncidentEvidenceLinkRecord.incident_id)
                .where(
                    IncidentEvidenceLinkRecord.evidence_event_id == evidence_id,
                    IncidentEvidenceLinkRecord.is_active.is_(True),
                )
                .order_by(IncidentEvidenceLinkRecord.incident_id)
            ).all()
        )


def _count(factory: sessionmaker[Session], model: type[Any]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_same_machine_component_compatible_event_inside_window_links_existing(
    linking_env: dict[str, Any],
) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    first_id = linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="inside-1",
            at=base,
            event_type="HYDRAULIC_PRESSURE_WARNING",
        )
    )
    second_id = linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="inside-2",
            at=base + timedelta(minutes=25),
            event_type="HYDRAULIC_PRESSURE_LOW",
        )
    )

    first_incidents = _incident_ids_for_evidence(linking_env["factory"], first_id)
    second_incidents = _incident_ids_for_evidence(linking_env["factory"], second_id)
    assert first_incidents == second_incidents
    assert len(first_incidents) == 1
    assert _count(linking_env["factory"], IncidentRecord) == 1

    with linking_env["factory"]() as session:
        second_link = session.scalar(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.evidence_event_id == second_id
            )
        )
        assert second_link is not None
        assert second_link.deterministic_rule_identifier == "test.rule.v1"
        assert "compatible event types" in second_link.link_reason
        assert "25" in second_link.link_reason or "1500.000s" in second_link.link_reason


def test_outside_window_creates_new_incident(linking_env: dict[str, Any]) -> None:
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="outside-1",
            at=base,
            event_type="HYDRAULIC_PRESSURE_WARNING",
        )
    )
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="outside-2",
            at=base + timedelta(minutes=61),
            event_type="HYDRAULIC_PRESSURE_WARNING",
        )
    )

    assert _count(linking_env["factory"], IncidentRecord) == 2


def test_different_component_creates_new_incident(linking_env: dict[str, Any]) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="component-1",
            at=at,
            event_type="BRAKE_WARNING",
        )
    )
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a2"],
            record_id="component-2",
            at=at + timedelta(minutes=5),
            event_type="BRAKE_WARNING",
        )
    )

    assert _count(linking_env["factory"], IncidentRecord) == 2


def test_different_machine_creates_new_incident(linking_env: dict[str, Any]) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="machine-a",
            at=at,
            event_type="BRAKE_WARNING",
        )
    )
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_b"],
            component_id=linking_env["component_b1"],
            record_id="machine-b",
            at=at + timedelta(minutes=5),
            event_type="BRAKE_WARNING",
        )
    )

    assert _count(linking_env["factory"], IncidentRecord) == 2


def test_incompatible_event_relationship_creates_new_incident(
    linking_env: dict[str, Any],
) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="incompatible-1",
            at=at,
            event_type="BRAKE_WARNING",
        )
    )
    linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="incompatible-2",
            at=at + timedelta(minutes=5),
            event_type="BATTERY_FAULT",
        )
    )

    assert _count(linking_env["factory"], IncidentRecord) == 2


def test_deterministic_repeatability_with_identical_database_state(
    linking_env: dict[str, Any],
) -> None:
    factory = linking_env["factory"]
    machine_id = linking_env["machine_a"]
    component_id = linking_env["component_a1"]
    at = datetime(2026, 10, 2, 10, 0)

    # Use fixed IDs so both trial transactions observe byte-for-byte equivalent
    # candidate identities and tie-break inputs.
    incident_low = UUID("00000000-0000-0000-0000-000000000010")
    incident_high = UUID("00000000-0000-0000-0000-000000000020")
    anchor_low = UUID("00000000-0000-0000-0000-000000000100")
    anchor_high = UUID("00000000-0000-0000-0000-000000000200")
    incoming_id = UUID("00000000-0000-0000-0000-000000000300")

    with factory.begin() as session:
        session.add_all(
            [
                IncidentRecord(id=incident_low, machine_id=machine_id, status=IncidentStatus.OPEN),
                IncidentRecord(id=incident_high, machine_id=machine_id, status=IncidentStatus.OPEN),
            ]
        )
        session.flush()
        session.add_all(
            [
                EvidenceEventRecord(
                    id=anchor_low,
                    machine_id=machine_id,
                    component_id=component_id,
                    source_type="MACHINE_EVENT",
                    original_source_record_id="anchor-low",
                    original_timestamp=at,
                    canonical_event_type="TIE_EVENT",
                    canonical_payload={},
                    raw_source_payload={},
                    provenance={},
                ),
                EvidenceEventRecord(
                    id=anchor_high,
                    machine_id=machine_id,
                    component_id=component_id,
                    source_type="MACHINE_EVENT",
                    original_source_record_id="anchor-high",
                    original_timestamp=at,
                    canonical_event_type="TIE_EVENT",
                    canonical_payload={},
                    raw_source_payload={},
                    provenance={},
                ),
                EvidenceEventRecord(
                    id=incoming_id,
                    machine_id=machine_id,
                    component_id=component_id,
                    source_type="MACHINE_EVENT",
                    original_source_record_id="incoming-tie",
                    original_timestamp=at + timedelta(minutes=10),
                    canonical_event_type="TIE_EVENT",
                    canonical_payload={},
                    raw_source_payload={},
                    provenance={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                IncidentEvidenceLinkRecord(
                    id=uuid4(),
                    incident_id=incident_low,
                    evidence_event_id=anchor_low,
                    is_active=True,
                    relationship_type="RELATED",
                    deterministic_rule_identifier="seed",
                    link_reason="seed",
                ),
                IncidentEvidenceLinkRecord(
                    id=uuid4(),
                    incident_id=incident_high,
                    evidence_event_id=anchor_high,
                    is_active=True,
                    relationship_type="RELATED",
                    deterministic_rule_identifier="seed",
                    link_reason="seed",
                ),
            ]
        )

    chosen: list[UUID] = []
    for _ in range(2):
        with SQLAlchemyUnitOfWork(factory) as uow:
            incoming = uow.evidence_events.get(incoming_id)
            assert incoming is not None
            decision = linking_env["linker"].link_new_evidence(uow, incoming)
            chosen.append(decision.incident_id)
            uow.rollback()

    assert chosen == [incident_low, incident_low]


def test_audit_entries_created_and_duplicate_replay_adds_none(
    linking_env: dict[str, Any],
) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    request = _request(
        machine_id=linking_env["machine_a"],
        component_id=linking_env["component_a1"],
        record_id="audit-1",
        at=at,
        event_type="AUDIT_EVENT",
    )

    first_id = linking_env["ingestion"].ingest_machine_event(request)
    first_audit_count = _count(linking_env["factory"], IncidentAuditEventRecord)
    second_id = linking_env["ingestion"].ingest_machine_event(request)

    assert first_id == second_id
    assert first_audit_count == 2
    assert _count(linking_env["factory"], IncidentAuditEventRecord) == 2

    incident_id = _incident_ids_for_evidence(linking_env["factory"], first_id)[0]
    with linking_env["factory"]() as session:
        actions = session.scalars(
            select(IncidentAuditEventRecord.action).where(
                IncidentAuditEventRecord.incident_id == incident_id
            )
        ).all()
    assert set(actions) == {
        IncidentAuditAction.INCIDENT_CREATED,
        IncidentAuditAction.EVIDENCE_LINKED,
    }


def test_incident_and_evidence_retrieval_apis(linking_env: dict[str, Any]) -> None:
    at = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    evidence_id = linking_env["ingestion"].ingest_machine_event(
        _request(
            machine_id=linking_env["machine_a"],
            component_id=linking_env["component_a1"],
            record_id="api-1",
            at=at,
            event_type="API_EVENT",
        )
    )
    incident_id = _incident_ids_for_evidence(linking_env["factory"], evidence_id)[0]

    incident_response = linking_env["client"].get(f"/api/v1/incidents/{incident_id}")
    evidence_response = linking_env["client"].get(
        f"/api/v1/incidents/{incident_id}/evidence"
    )

    assert incident_response.status_code == 200
    assert incident_response.json()["incident_id"] == str(incident_id)
    assert incident_response.json()["status"] == "OPEN"
    assert len(incident_response.json()["audit_events"]) == 2

    assert evidence_response.status_code == 200
    payload = evidence_response.json()
    assert payload["incident_id"] == str(incident_id)
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["evidence_id"] == str(evidence_id)
    assert payload["evidence"][0]["deterministic_rule_identifier"] == "test.rule.v1"
