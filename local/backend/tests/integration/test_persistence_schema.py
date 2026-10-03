from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.session import create_database_engine
from app.domain.enums import (
    ContextQuality,
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.models import (
    AppendOnlyAuditViolation,
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceEventRecord,
    ImmutableContextSnapshotViolation,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DOMAIN_TABLES = {
    "machines",
    "components",
    "evidence_events",
    "evidence_attachments",
    "context_snapshots",
    "incidents",
    "incident_evidence_links",
    "incident_audit_events",
    "verification_rules",
    "verification_runs",
    "verification_evidence",
    "handover_packets",
    "handover_items",
    "operating_sessions",
    "machine_session_reports",
    "sync_outbox_items",
    "sync_conflicts",
}


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _run_alembic(database_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MINE_TRACE_DATABASE_URL"] = _database_url(database_path)
    env["MINE_TRACE_SQLITE_WAL_ENABLED"] = "false"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _make_engine(database_path: Path):
    return create_database_engine(
        Settings(
            environment="test",
            database_url=_database_url(database_path),
            sqlite_wal_enabled=False,
        )
    )


def test_empty_database_upgrades_to_head_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"

    _run_alembic(database_path, "upgrade", "head")
    # A second upgrade must be a no-op rather than fail or duplicate schema.
    _run_alembic(database_path, "upgrade", "head")

    engine = _make_engine(database_path)
    try:
        inspector = inspect(engine)
        assert EXPECTED_DOMAIN_TABLES.issubset(set(inspector.get_table_names()))

        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("evidence_events")
        }
        assert "uq_evidence_events_source_original_record" in unique_constraints

        evidence_fks = inspector.get_foreign_keys("evidence_events")
        assert any(
            fk["referred_table"] == "machines"
            and fk["constrained_columns"] == ["machine_id"]
            for fk in evidence_fks
        )
        assert any(
            fk["referred_table"] == "components"
            and fk["constrained_columns"] == ["component_id", "machine_id"]
            for fk in evidence_fks
        )

        evidence_indexes = {
            index["name"] for index in inspector.get_indexes("evidence_events")
        }
        assert {
            "ix_evidence_events_machine_timeline",
            "ix_evidence_events_component_timeline",
            "ix_evidence_events_original_timestamp",
            "ix_evidence_events_ingestion_timestamp",
        }.issubset(evidence_indexes)

        link_indexes = {
            index["name"] for index in inspector.get_indexes("incident_evidence_links")
        }
        assert {
            "ix_incident_evidence_links_incident_retrieval",
            "ix_incident_evidence_links_evidence_retrieval",
            "ix_incident_evidence_links_active_incident",
        }.issubset(link_indexes)

        verification_indexes = {
            index["name"] for index in inspector.get_indexes("verification_runs")
        }
        assert {
            "ix_verification_runs_incident_lookup",
            "ix_verification_runs_rule_lookup",
        }.issubset(verification_indexes)

        handover_item_indexes = {
            index["name"] for index in inspector.get_indexes("handover_items")
        }
        assert {
            "ix_handover_items_packet_id",
            "ix_handover_items_incident_id",
        }.issubset(handover_item_indexes)

        attachment_columns = {
            column["name"] for column in inspector.get_columns("evidence_attachments")
        }
        assert {
            "attachment_type",
            "storage_reference",
            "mime_type",
            "file_size",
            "checksum",
            "created_at",
        }.issubset(attachment_columns)

        attachment_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("evidence_attachments")
        }
        assert "ck_evidence_attachments_file_size_nonnegative" in attachment_checks

        context_columns = {
            column["name"]: column for column in inspector.get_columns("context_snapshots")
        }
        assert context_columns["quality"]["nullable"] is True
    finally:
        engine.dispose()


def test_evidence_uniqueness_foreign_keys_and_persistence_survive_reopen(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "persistence.db"
    _run_alembic(database_path, "upgrade", "head")

    machine_id = uuid4()
    component_id = uuid4()
    evidence_id = uuid4()
    snapshot_id = uuid4()

    engine = _make_engine(database_path)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    try:
        with SessionLocal.begin() as session:
            session.add(MachineRecord(id=machine_id))
            session.flush()
            session.add(ComponentRecord(id=component_id, machine_id=machine_id))
            session.flush()
            session.add(
                EvidenceEventRecord(
                    id=evidence_id,
                    machine_id=machine_id,
                    component_id=component_id,
                    source_type="ECU",
                    original_source_record_id="record-001",
                    original_timestamp=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
                    canonical_event_type="HYDRAULIC_PRESSURE_WARNING",
                    canonical_payload={"pressure_kpa": 1700},
                    raw_source_payload={"fault": "HP_LOW", "pressure": 1700},
                    provenance={"source_file": "ecu-2026-10-02.json"},
                )
            )
            session.flush()
            session.add(
                ContextSnapshotRecord(
                    id=snapshot_id,
                    evidence_event_id=evidence_id,
                    quality=ContextQuality.KNOWN,
                    snapshot_payload={"shift": "A", "location": "level-4"},
                )
            )
    finally:
        engine.dispose()

    # Reopen with an entirely new Engine/Session factory and verify durability.
    reopened_engine = _make_engine(database_path)
    ReopenedSession = sessionmaker(
        bind=reopened_engine,
        expire_on_commit=False,
        class_=Session,
    )
    try:
        with ReopenedSession() as session:
            persisted = session.scalar(
                select(EvidenceEventRecord).where(EvidenceEventRecord.id == evidence_id)
            )
            assert persisted is not None
            assert persisted.machine_id == machine_id
            assert persisted.component_id == component_id
            assert persisted.raw_source_payload["fault"] == "HP_LOW"
            assert persisted.provenance["source_file"] == "ecu-2026-10-02.json"

        with ReopenedSession() as session:
            snapshot = session.get(ContextSnapshotRecord, snapshot_id)
            assert snapshot is not None
            snapshot.snapshot_payload = {"shift": "CURRENT", "location": "elsewhere"}
            with pytest.raises(ImmutableContextSnapshotViolation):
                session.commit()
            session.rollback()

        with ReopenedSession() as session:
            session.add(
                EvidenceEventRecord(
                    id=uuid4(),
                    machine_id=machine_id,
                    component_id=component_id,
                    source_type="ECU",
                    original_source_record_id="record-001",
                    original_timestamp=datetime(2026, 10, 2, 12, 1, tzinfo=timezone.utc),
                    canonical_event_type="DUPLICATE_SHOULD_FAIL",
                    canonical_payload={},
                    raw_source_payload={},
                    provenance={},
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        with ReopenedSession() as session:
            session.add(ComponentRecord(id=uuid4(), machine_id=uuid4()))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        reopened_engine.dispose()


def test_component_must_belong_to_same_machine_as_evidence(tmp_path: Path) -> None:
    database_path = tmp_path / "component_machine.db"
    _run_alembic(database_path, "upgrade", "head")
    engine = _make_engine(database_path)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    machine_a = uuid4()
    machine_b = uuid4()
    component_b = uuid4()

    try:
        with SessionLocal.begin() as session:
            session.add_all(
                [
                    MachineRecord(id=machine_a),
                    MachineRecord(id=machine_b),
                ]
            )
            session.flush()
            session.add(ComponentRecord(id=component_b, machine_id=machine_b))

        with SessionLocal() as session:
            session.add(
                EvidenceEventRecord(
                    id=uuid4(),
                    machine_id=machine_a,
                    component_id=component_b,
                    source_type="OPERATOR_NOTE",
                    original_source_record_id="note-001",
                    original_timestamp=datetime.now(timezone.utc),
                    canonical_event_type="OBSERVATION",
                    canonical_payload={"text": "grinding noise"},
                    raw_source_payload={"text": "grinding noise"},
                    provenance={"operator_ref": "operator-7"},
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_active_incident_link_is_unique_and_audit_is_orm_append_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "incident_integrity.db"
    _run_alembic(database_path, "upgrade", "head")
    engine = _make_engine(database_path)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    machine_id = uuid4()
    evidence_id = uuid4()
    incident_id = uuid4()
    audit_id = uuid4()

    try:
        with SessionLocal.begin() as session:
            session.add(MachineRecord(id=machine_id))
            session.flush()
            session.add(
                EvidenceEventRecord(
                    id=evidence_id,
                    machine_id=machine_id,
                    component_id=None,
                    source_type="TECHNICIAN_NOTE",
                    original_source_record_id="tech-001",
                    original_timestamp=datetime.now(timezone.utc),
                    canonical_event_type="MAINTENANCE_OBSERVATION",
                    canonical_payload={"text": "pump replaced"},
                    raw_source_payload={"note": "pump replaced"},
                    provenance={"work_order": "WO-17"},
                )
            )
            session.flush()
            session.add(
                IncidentRecord(
                    id=incident_id,
                    machine_id=machine_id,
                    status=IncidentStatus.OPEN,
                )
            )

        with SessionLocal.begin() as session:
            session.add(
                IncidentEvidenceLinkRecord(
                    id=uuid4(),
                    incident_id=incident_id,
                    evidence_event_id=evidence_id,
                    relationship_type=IncidentEvidenceRelationshipType.RELATED,
                    deterministic_rule_identifier="link.same-machine-window.v1",
                    link_reason="same machine within configured incident window",
                )
            )
            session.add(
                IncidentAuditEventRecord(
                    id=audit_id,
                    incident_id=incident_id,
                    action=IncidentAuditAction.EVIDENCE_LINKED,
                    occurred_at=datetime.now(timezone.utc),
                    payload={"evidence_event_id": str(evidence_id)},
                )
            )

        with SessionLocal() as session:
            session.add(
                IncidentEvidenceLinkRecord(
                    id=uuid4(),
                    incident_id=incident_id,
                    evidence_event_id=evidence_id,
                    relationship_type=IncidentEvidenceRelationshipType.RELATED,
                    deterministic_rule_identifier="link.same-machine-window.v1",
                    link_reason="duplicate active association",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        with SessionLocal() as session:
            audit = session.get(IncidentAuditEventRecord, audit_id)
            assert audit is not None
            audit.payload = {"tampered": True}
            with pytest.raises(AppendOnlyAuditViolation):
                session.commit()
            session.rollback()

        with SessionLocal() as session:
            audit = session.get(IncidentAuditEventRecord, audit_id)
            assert audit is not None
            session.delete(audit)
            with pytest.raises(AppendOnlyAuditViolation):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()



def test_previous_head_upgrades_to_asset_metadata_head_without_data_loss(tmp_path: Path) -> None:
    database_path = tmp_path / "previous-head-upgrade.db"
    _run_alembic(database_path, "upgrade", "c6f3e92a4d11")

    machine_id = uuid4()
    component_id = uuid4()
    evidence_id = uuid4()
    incident_id = uuid4()
    audit_id = uuid4()
    rule_id = uuid4()
    run_id = uuid4()
    handover_id = uuid4()
    handover_item_id = uuid4()

    engine = _make_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO machines (id) VALUES (:id)"), {"id": machine_id.hex})
            connection.execute(
                text("INSERT INTO components (id, machine_id) VALUES (:id, :machine_id)"),
                {"id": component_id.hex, "machine_id": machine_id.hex},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO evidence_events (
                        id, machine_id, component_id, source_type,
                        original_source_record_id, original_timestamp,
                        canonical_event_type, canonical_payload,
                        raw_source_payload, provenance
                    ) VALUES (
                        :id, :machine_id, :component_id, 'MACHINE_EVENT',
                        'legacy-source-1', '2026-10-02 12:00:00',
                        'LEGACY_EVENT', '{}', '{}', '{}'
                    )
                    """
                ),
                {
                    "id": evidence_id.hex,
                    "machine_id": machine_id.hex,
                    "component_id": component_id.hex,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO incidents (id, machine_id, status) "
                    "VALUES (:id, :machine_id, 'OPEN')"
                ),
                {"id": incident_id.hex, "machine_id": machine_id.hex},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO incident_audit_events (id, incident_id, action, occurred_at, payload)
                    VALUES (:id, :incident_id, 'INCIDENT_CREATED', '2026-10-02 12:01:00', '{}')
                    """
                ),
                {"id": audit_id.hex, "incident_id": incident_id.hex},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO verification_rules (id, identifier, name, rule_type, window_minutes)
                    VALUES (:id, 'legacy-rule', 'Legacy Rule', 'NO_EVENT', 30)
                    """
                ),
                {"id": rule_id.hex},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO verification_runs (
                        id, incident_id, verification_rule_id, started_at, window_ends_at
                    ) VALUES (
                        :id, :incident_id, :rule_id,
                        '2026-10-02 12:02:00', '2026-10-02 12:32:00'
                    )
                    """
                ),
                {"id": run_id.hex, "incident_id": incident_id.hex, "rule_id": rule_id.hex},
            )
            connection.execute(
                text("INSERT INTO handover_packets (id) VALUES (:id)"),
                {"id": handover_id.hex},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO handover_items (
                        id, handover_packet_id, incident_id, status_snapshot
                    ) VALUES (:id, :packet_id, :incident_id, 'OPEN')
                    """
                ),
                {
                    "id": handover_item_id.hex,
                    "packet_id": handover_id.hex,
                    "incident_id": incident_id.hex,
                },
            )
    finally:
        engine.dispose()

    _run_alembic(database_path, "upgrade", "head")

    upgraded_engine = _make_engine(database_path)
    try:
        inspector = inspect(upgraded_engine)
        machine_columns = {column["name"]: column for column in inspector.get_columns("machines")}
        component_columns = {column["name"]: column for column in inspector.get_columns("components")}
        for column in (
            "display_name",
            "asset_code",
            "machine_type",
            "manufacturer",
            "model",
            "site_name",
            "site_area",
        ):
            assert machine_columns[column]["nullable"] is True
        for column in ("display_name", "component_type", "manufacturer", "model"):
            assert component_columns[column]["nullable"] is True

        with upgraded_engine.connect() as connection:
            for table in (
                "machines",
                "components",
                "evidence_events",
                "incidents",
                "incident_audit_events",
                "verification_runs",
                "handover_packets",
                "handover_items",
            ):
                assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 1

        SessionLocal = sessionmaker(bind=upgraded_engine, expire_on_commit=False, class_=Session)
        with SessionLocal() as session:
            legacy_machine = session.get(MachineRecord, machine_id)
            legacy_component = session.get(ComponentRecord, component_id)
            legacy_evidence = session.get(EvidenceEventRecord, evidence_id)
            assert legacy_machine is not None
            assert legacy_machine.display_name is None
            assert legacy_machine.asset_code is None
            assert legacy_component is not None
            assert legacy_component.display_name is None
            assert legacy_evidence is not None
            # The operating-session migration is intentionally non-inferential:
            # pre-existing evidence has no fabricated historical session identity.
            assert legacy_evidence.session_id is None
    finally:
        upgraded_engine.dispose()

    current = _run_alembic(database_path, "current")
    assert "b72d6e31c9f0" in current.stdout
