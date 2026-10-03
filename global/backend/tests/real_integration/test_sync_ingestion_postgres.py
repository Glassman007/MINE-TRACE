"""Opt-in real PostgreSQL acceptance for transactional global sync ingestion."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.contracts.sync import SyncAcknowledgementStatus, parse_sync_envelope, with_computed_checksum
from app.models import EvidenceEventRecord, SessionReportRecord, SyncConflictRecord, SyncReceiptRecord
from app.services.sync_ingestion import GlobalSyncIngestionService
from tests.sync_test_data import ZERO_CHECKSUM, signed_envelope

pytestmark = pytest.mark.real_postgres


def _enabled() -> bool:
    return os.getenv("MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION") == "1"


def test_transactional_sync_idempotency_and_conflict_on_real_postgresql() -> None:
    if not _enabled():
        pytest.skip("set MINE_TRACE_RUN_REAL_POSTGRES_INTEGRATION=1 to run real PostgreSQL sync acceptance")
    url = os.getenv("MINE_TRACE_TEST_POSTGRES_URL")
    if not url:
        pytest.fail("MINE_TRACE_TEST_POSTGRES_URL is required when real PostgreSQL integration is enabled")
    pytest.importorskip("psycopg")

    engine = create_engine(url, pool_pre_ping=True)
    schema = f"mine_trace_sync_{uuid4().hex[:12]}"
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))

    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.commit()
        try:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()

            accepted_envelope = signed_envelope()
            with Session(bind=connection, expire_on_commit=False) as session:
                accepted = GlobalSyncIngestionService(session).ingest(accepted_envelope)
                assert accepted.acknowledgement.status is SyncAcknowledgementStatus.ACCEPTED

            with Session(bind=connection, expire_on_commit=False) as session:
                redelivery = GlobalSyncIngestionService(session).ingest(accepted_envelope)
                assert redelivery.acknowledgement == accepted.acknowledgement

            payload = accepted_envelope.model_dump(mode="json")
            payload["package_id"] = str(uuid4())
            payload["machine_session_report"]["machine"]["display_name"] = "conflicting revision"
            payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
            conflict_envelope = with_computed_checksum(parse_sync_envelope(payload))
            with Session(bind=connection, expire_on_commit=False) as session:
                conflict = GlobalSyncIngestionService(session).ingest(conflict_envelope)
                assert conflict.acknowledgement.status is SyncAcknowledgementStatus.CONFLICT

            with Session(bind=connection) as session:
                assert session.scalar(select(func.count()).select_from(EvidenceEventRecord)) == 1
                assert session.scalar(select(func.count()).select_from(SessionReportRecord)) == 1
                assert session.scalar(select(func.count()).select_from(SyncReceiptRecord)) == 2
                assert session.scalar(select(func.count()).select_from(SyncConflictRecord)) == 1
        finally:
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()
