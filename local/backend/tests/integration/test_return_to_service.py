from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.domain.enums import IncidentStatus, ReturnToServiceState, VerificationRuleType, VerificationRunResult
from app.models import IncidentRecord, MachineRecord, VerificationRuleRecord, VerificationRunRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.return_to_service import ReturnToServiceService


def _env(tmp_path: Path, **overrides):
    machine_id = uuid4()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'rts.db'}",
        sqlite_wal_enabled=False,
        local_machine_id=machine_id,
        **overrides,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
    return settings, engine, factory, machine_id


def test_cleared_when_no_configured_blocker_exists(tmp_path: Path) -> None:
    settings, engine, factory, _ = _env(tmp_path)
    result = ReturnToServiceService(settings, lambda: SQLAlchemyUnitOfWork(factory)).evaluate()
    assert result.state is ReturnToServiceState.CLEARED
    assert result.blocking_reasons == []
    assert result.policy_identifier == settings.return_to_service_policy_identifier
    assert result.policy_revision == settings.return_to_service_policy_revision
    engine.dispose()


def test_pending_verification_survives_restart_and_requires_verification(tmp_path: Path) -> None:
    settings, engine, factory, machine_id = _env(tmp_path)
    incident_id, rule_id, run_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.VERIFYING))
        session.add(VerificationRuleRecord(id=rule_id, identifier="rts-test", name="RTS test", rule_type=VerificationRuleType.NO_EVENT, window_minutes=30))
        session.add(VerificationRunRecord(id=run_id, incident_id=incident_id, verification_rule_id=rule_id, started_at=now, window_ends_at=now, completed_at=None, result=None))

    # Recreate the service to model a process restart; authority is persisted SQLite state.
    restarted = ReturnToServiceService(settings, lambda: SQLAlchemyUnitOfWork(factory))
    result = restarted.evaluate()
    assert result.state is ReturnToServiceState.VERIFICATION_REQUIRED
    assert run_id in result.verification_ids
    assert incident_id in result.incident_ids
    assert {r.code for r in result.blocking_reasons} >= {"VERIFICATION_RUN_PENDING"}
    engine.dispose()


def test_explicit_typed_policy_can_produce_do_not_return(tmp_path: Path) -> None:
    settings, engine, factory, machine_id = _env(
        tmp_path,
        return_to_service_do_not_return_incident_statuses=(IncidentStatus.RECURRED,),
    )
    incident_id = uuid4()
    with factory.begin() as session:
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.RECURRED))
    result = ReturnToServiceService(settings, lambda: SQLAlchemyUnitOfWork(factory)).evaluate()
    assert result.state is ReturnToServiceState.DO_NOT_RETURN
    assert result.incident_ids == [incident_id]
    assert result.blocking_reasons[0].code == "INCIDENT_STATUS_BLOCKS_RETURN"
    engine.dispose()


def test_explicit_verification_result_policy_can_block(tmp_path: Path) -> None:
    settings, engine, factory, machine_id = _env(
        tmp_path,
        return_to_service_do_not_return_verification_results=(VerificationRunResult.RECURRENCE_DETECTED,),
    )
    incident_id, rule_id, run_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.RECURRED))
        session.add(VerificationRuleRecord(id=rule_id, identifier="rts-result", name="RTS result", rule_type=VerificationRuleType.NO_EVENT, window_minutes=30))
        session.add(VerificationRunRecord(id=run_id, incident_id=incident_id, verification_rule_id=rule_id, started_at=now, window_ends_at=now, completed_at=now, result=VerificationRunResult.RECURRENCE_DETECTED))
    result = ReturnToServiceService(settings, lambda: SQLAlchemyUnitOfWork(factory)).evaluate()
    assert result.state is ReturnToServiceState.DO_NOT_RETURN
    assert result.verification_ids == [run_id]
    engine.dispose()


def test_semantic_and_ai_failures_cannot_change_return_to_service(tmp_path: Path, monkeypatch) -> None:
    settings, engine, factory, _ = _env(tmp_path)

    def explode(*args, **kwargs):
        raise AssertionError("semantic/AI integration must not be called by return-to-service")

    monkeypatch.setattr("app.integrations.qdrant.client.QdrantService.vector_search", explode)
    monkeypatch.setattr("app.integrations.embeddings.factory.build_embedding_provider", explode)
    monkeypatch.setattr("app.integrations.llm.factory.build_ai_provider", explode)

    result = ReturnToServiceService(settings, lambda: SQLAlchemyUnitOfWork(factory)).evaluate()
    assert result.state is ReturnToServiceState.CLEARED
    engine.dispose()
