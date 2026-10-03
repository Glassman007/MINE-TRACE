from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork


@pytest.fixture
def session_factory(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    database_path = tmp_path / "repository.db"
    engine = create_sqlite_test_engine(database_path)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    try:
        yield factory
    finally:
        engine.dispose()


def _uow(factory: sessionmaker[Session]) -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork(factory)


def _evidence(evidence_id: UUID, machine_id: UUID, source_record_id: str) -> EvidenceEventRecord:
    return EvidenceEventRecord(
        id=evidence_id,
        machine_id=machine_id,
        source_machine_id=machine_id,
        component_id=None,
        source_type="TEST_SOURCE",
        original_source_record_id=source_record_id,
        original_timestamp=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        canonical_event_type="TEST_EVENT",
        canonical_payload={"value": 1},
        raw_source_payload={"raw": True},
        provenance={"test": True},
    )


def test_successful_transaction_commit(session_factory: sessionmaker[Session]) -> None:
    machine_id = uuid4()

    with _uow(session_factory) as uow:
        uow.machines.add(MachineRecord(id=machine_id))
        uow.commit()


def test_persistence_after_commit(session_factory: sessionmaker[Session]) -> None:
    machine_id = uuid4()

    with _uow(session_factory) as uow:
        uow.machines.add(MachineRecord(id=machine_id))
        uow.commit()

    with _uow(session_factory) as uow:
        persisted = uow.machines.get(machine_id)
        assert persisted is not None
        assert persisted.id == machine_id


def test_rollback_after_forced_exception(session_factory: sessionmaker[Session]) -> None:
    machine_id = uuid4()

    with pytest.raises(RuntimeError, match="forced failure"):
        with _uow(session_factory) as uow:
            uow.machines.add(MachineRecord(id=machine_id))
            # Force SQL execution before the exception so rollback is exercised
            # against an actual open database transaction.
            uow.flush()
            raise RuntimeError("forced failure")

    with _uow(session_factory) as uow:
        assert uow.machines.get(machine_id) is None


def test_explicit_rollback_leaves_no_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    machine_id = uuid4()

    with _uow(session_factory) as uow:
        uow.machines.add(MachineRecord(id=machine_id))
        uow.flush()
        uow.rollback()

    with _uow(session_factory) as uow:
        assert uow.machines.get(machine_id) is None


def test_uncommitted_context_exit_rolls_back(session_factory: sessionmaker[Session]) -> None:
    machine_id = uuid4()

    with _uow(session_factory) as uow:
        uow.machines.add(MachineRecord(id=machine_id))
        uow.flush()
        # No commit: normal context exit must not persist accidental work.

    with _uow(session_factory) as uow:
        assert uow.machines.get(machine_id) is None


def test_audit_repository_is_append_only_and_evidence_has_no_delete_primitive(
    session_factory: sessionmaker[Session],
) -> None:
    machine_id = uuid4()
    incident_id = uuid4()
    audit_id = uuid4()

    with _uow(session_factory) as uow:
        uow.machines.add(MachineRecord(id=machine_id))
        uow.flush()
        uow.incidents.add(
            IncidentRecord(
                id=incident_id,
                machine_id=machine_id,
                status=IncidentStatus.OPEN,
            )
        )
        uow.flush()

        assert not hasattr(uow.incident_audit_events, "update")
        assert not hasattr(uow.incident_audit_events, "delete")
        assert not hasattr(uow.evidence_events, "delete")

        uow.incident_audit_events.add(
            IncidentAuditEventRecord(
                id=audit_id,
                incident_id=incident_id,
                action=IncidentAuditAction.INCIDENT_CREATED,
                occurred_at=datetime.now(timezone.utc),
                payload={},
            )
        )
        uow.commit()

    with _uow(session_factory) as uow:
        audit = uow.incident_audit_events.get(audit_id)
        assert audit is not None
        assert audit.action is IncidentAuditAction.INCIDENT_CREATED
        assert [event.id for event in uow.incident_audit_events.list_for_incident(incident_id)] == [
            audit_id
        ]
