"""Opt-in acceptance test for the fresh global Alembic history on real PostgreSQL.

Required environment:
    MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION=1
    MINE_TRACE_TEST_POSTGRES_URL=postgresql+psycopg://...
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.domain.enums import IncidentStatus
from app.models import EvidenceEventRecord, MachineRecord, OperatingSessionRecord, SessionReportRecord

pytestmark = pytest.mark.real_postgres


def _enabled() -> bool:
    return os.getenv("MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION") == "1"


def test_fresh_migration_and_revision_persistence_against_postgresql() -> None:
    if not _enabled():
        pytest.skip("set MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION=1 to run real PostgreSQL schema acceptance")
    url = os.getenv("MINE_TRACE_TEST_POSTGRES_URL")
    if not url:
        pytest.fail("MINE_TRACE_TEST_POSTGRES_URL is required when real PostgreSQL integration is enabled")
    pytest.importorskip("psycopg")

    engine = create_engine(url, pool_pre_ping=True)
    schema = f"mine_trace_global_{uuid4().hex[:12]}"
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))

    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.commit()
        try:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

            tables = set(inspect(connection).get_table_names(schema=schema))
            assert {
                "machines", "components", "sessions", "incidents",
                "incident_session_links", "evidence_events",
                "incident_evidence_links", "maintenance_actions",
                "verification_runs", "session_reports", "sync_receipts", "sync_conflicts",
            } <= tables

            now = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
            machine_id = uuid4()
            session_id = uuid4()
            evidence_id = uuid4()
            with Session(bind=connection, expire_on_commit=False) as session:
                session.add(MachineRecord(id=machine_id, display_name="acceptance-machine"))
                session.add(OperatingSessionRecord(id=session_id, machine_id=machine_id, started_at=now, state="CLOSED", latest_report_revision=2))
                session.flush()
                original_time = now - timedelta(hours=2)
                ingested_time = now
                session.add(EvidenceEventRecord(
                    id=evidence_id,
                    machine_id=machine_id,
                    source_machine_id=machine_id,
                    session_id=session_id,
                    component_id=None,
                    source_type="HUMAN_OBSERVATION",
                    original_source_record_id="edge-record-17",
                    original_timestamp=original_time,
                    ingestion_timestamp=ingested_time,
                    source_report_revision=2,
                    canonical_event_type="OPERATOR_NOTE",
                    canonical_payload={"text": "hydraulic whine"},
                    raw_source_payload={"text": "hydraulic whine"},
                    provenance={"edge": "machine"},
                ))
                for revision in (1, 2):
                    session.add(SessionReportRecord(
                        id=uuid4(), report_id=uuid4(), source_machine_id=machine_id,
                        session_id=session_id, schema_version="1.0", report_revision=revision,
                        generated_at=now, checksum=f"checksum-{revision}", payload={"revision": revision},
                    ))
                session.commit()

                persisted = session.get(EvidenceEventRecord, evidence_id)
                assert persisted is not None
                assert persisted.id == evidence_id
                assert persisted.original_timestamp == original_time
                assert persisted.ingestion_timestamp == ingested_time
                reports = session.query(SessionReportRecord).filter_by(session_id=session_id).order_by(SessionReportRecord.report_revision).all()
                assert [report.report_revision for report in reports] == [1, 2]
                assert [report.payload["revision"] for report in reports] == [1, 2]
        finally:
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()
