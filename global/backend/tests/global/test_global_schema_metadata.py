from __future__ import annotations

from pathlib import Path

from sqlalchemy import UniqueConstraint

from app.db.base import Base
import app.models  # noqa: F401


REQUIRED_TABLES = {
    "machines",
    "components",
    "sessions",
    "incidents",
    "incident_session_links",
    "evidence_events",
    "incident_evidence_links",
    "maintenance_actions",
    "verification_runs",
    "session_reports",
    "sync_receipts",
    "sync_conflicts",
    "semantic_index_outbox",
}


def test_global_metadata_contains_required_canonical_tables() -> None:
    assert REQUIRED_TABLES <= set(Base.metadata.tables)


def test_key_relationship_foreign_keys_exist() -> None:
    expected = {
        ("components", "machine_id", "machines.id"),
        ("sessions", "machine_id", "machines.id"),
        ("incidents", "machine_id", "machines.id"),
        ("incident_session_links", "incident_id", "incidents.id"),
        ("incident_session_links", "session_id", "sessions.id"),
        ("evidence_events", "session_id", "sessions.id"),
        ("incident_evidence_links", "incident_id", "incidents.id"),
        ("incident_evidence_links", "evidence_event_id", "evidence_events.id"),
        ("maintenance_actions", "incident_id", "incidents.id"),
        ("verification_runs", "incident_id", "incidents.id"),
        ("session_reports", "session_id", "sessions.id"),
        ("sync_receipts", "session_id", "sessions.id"),
        ("sync_conflicts", "session_id", "sessions.id"),
    }
    actual: set[tuple[str, str, str]] = set()
    for table_name, column_name, target in expected:
        column = Base.metadata.tables[table_name].c[column_name]
        actual.update((table_name, column_name, fk.target_fullname) for fk in column.foreign_keys)
    assert expected <= actual


def test_evidence_preserves_event_time_separately_from_central_ingestion_time() -> None:
    evidence = Base.metadata.tables["evidence_events"]
    assert evidence.c.original_timestamp is not evidence.c.ingestion_timestamp
    assert evidence.c.original_timestamp.type.timezone is True
    assert evidence.c.ingestion_timestamp.type.timezone is True
    assert evidence.c.ingestion_timestamp.server_default is not None
    assert evidence.c.source_machine_id.nullable is False


def test_stable_evidence_uuid_is_primary_identity_and_source_identity_is_constrained() -> None:
    evidence = Base.metadata.tables["evidence_events"]
    assert evidence.c.id.primary_key
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in evidence.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("source_machine_id", "source_type", "original_source_record_id") in unique_columns


def test_session_report_revisions_are_preserved_not_overwritten() -> None:
    reports = Base.metadata.tables["session_reports"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in reports.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("source_machine_id", "session_id", "report_revision") in unique_columns
    assert reports.c.payload.nullable is False
    assert reports.c.ingested_at.server_default is not None


def test_postgresql_partial_index_has_no_sqlite_dialect_clause() -> None:
    table = Base.metadata.tables["incident_evidence_links"]
    index = next(index for index in table.indexes if index.name == "ix_incident_evidence_links_active_incident")
    assert index.dialect_options["postgresql"].get("where") is not None
    assert index.dialect_options["sqlite"].get("where") is None


def test_global_alembic_history_starts_fresh_then_adds_semantic_outbox() -> None:
    root = Path(__file__).resolve().parents[2]
    revisions = sorted((root / "migrations" / "versions").glob("*.py"))
    assert [path.name for path in revisions] == [
        "0001_global_initial.py",
        "0002_semantic_index_outbox.py",
    ]
    initial = revisions[0].read_text()
    outbox = revisions[1].read_text()
    assert 'down_revision = None' in initial
    assert 'revision = "0001_global_initial"' in initial
    assert 'down_revision = "0001_global_initial"' in outbox
    assert 'revision = "0002_semantic_index_outbox"' in outbox
