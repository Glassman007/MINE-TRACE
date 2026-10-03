from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.main import app
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.incident_correction import (
    CorrectionStage,
    IncidentCorrectionService,
)


class InjectedCorrectionFailure(RuntimeError):
    pass


@pytest.fixture
def correction_env(tmp_path) -> Generator[dict[str, Any], None, None]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'correction.db'}",
        sqlite_wal_enabled=False,
        incident_correction_rule_identifier="test.correction.v1",
        incident_correction_rule_name="Test explicit correction",
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_id = uuid4()
    source_incident_id = uuid4()
    target_incident_id = uuid4()
    evidence_id = uuid4()
    old_link_id = uuid4()
    at = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add_all(
            [
                IncidentRecord(
                    id=source_incident_id,
                    machine_id=machine_id,
                    status=IncidentStatus.OPEN,
                ),
                IncidentRecord(
                    id=target_incident_id,
                    machine_id=machine_id,
                    status=IncidentStatus.OPEN,
                ),
            ]
        )
        session.flush()
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                component_id=None,
                source_type="MACHINE_EVENT",
                original_source_record_id="correction-source-1",
                original_timestamp=at,
                canonical_event_type="BRAKE_WARNING",
                canonical_payload={"code": "B1"},
                raw_source_payload={"raw": "B1"},
                provenance={"source": "ecu"},
            )
        )
        session.flush()
        session.add(
            IncidentEvidenceLinkRecord(
                id=old_link_id,
                incident_id=source_incident_id,
                evidence_event_id=evidence_id,
                is_active=True,
                relationship_type=IncidentEvidenceRelationshipType.RELATED,
                deterministic_rule_identifier="seed.rule",
                link_reason="seed association",
                linked_at=at,
            )
        )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)
    client.__enter__()
    try:
        yield {
            "settings": settings,
            "engine": engine,
            "factory": factory,
            "client": client,
            "machine_id": machine_id,
            "source_incident_id": source_incident_id,
            "target_incident_id": target_incident_id,
            "evidence_id": evidence_id,
            "old_link_id": old_link_id,
            "at": at,
        }
    finally:
        client.__exit__(None, None, None)
        app.dependency_overrides.clear()
        engine.dispose()


def _service(env: dict[str, Any], *, fault_stage: CorrectionStage | None = None):
    def fault_hook(stage: CorrectionStage) -> None:
        if stage == fault_stage:
            raise InjectedCorrectionFailure(stage.value)

    return IncidentCorrectionService(
        lambda: SQLAlchemyUnitOfWork(env["factory"]),
        settings=env["settings"],
        clock=lambda: datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc),
        fault_hook=fault_hook if fault_stage is not None else None,
    )


def _count(factory, model) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def _assert_split_rollback_intact(env: dict[str, Any]) -> None:
    with env["factory"]() as session:
        evidence = session.get(EvidenceEventRecord, env["evidence_id"])
        old_link = session.get(IncidentEvidenceLinkRecord, env["old_link_id"])
        incidents = session.scalars(select(IncidentRecord).order_by(IncidentRecord.id)).all()
        links = session.scalars(
            select(IncidentEvidenceLinkRecord).order_by(IncidentEvidenceLinkRecord.id)
        ).all()
        audits = session.scalars(select(IncidentAuditEventRecord)).all()

        assert evidence is not None  # source evidence is never deleted by correction
        assert old_link is not None
        assert old_link.is_active is True
        assert old_link.unlinked_at is None
        assert len(incidents) == 2  # source + pre-seeded target only; no split incident survived
        assert len(links) == 1
        assert links[0].id == env["old_link_id"]
        assert links[0].incident_id == env["source_incident_id"]
        assert links[0].is_active is True
        assert audits == []


@pytest.mark.parametrize(
    "fault_stage",
    [
        CorrectionStage.OLD_LINK_DEACTIVATED,
        CorrectionStage.EVIDENCE_UNLINKED_AUDIT_APPENDED,
        CorrectionStage.NEW_INCIDENT_CREATED,
        CorrectionStage.NEW_LINK_CREATED,
        CorrectionStage.EVIDENCE_LINKED_AUDIT_APPENDED,
        CorrectionStage.INCIDENT_SPLIT_AUDIT_APPENDED,
    ],
)
def test_split_rolls_back_every_intermediate_stage(
    correction_env: dict[str, Any], fault_stage: CorrectionStage
) -> None:
    with pytest.raises(InjectedCorrectionFailure):
        _service(correction_env, fault_stage=fault_stage).split_incident(
            source_incident_id=correction_env["source_incident_id"],
            evidence_ids=[correction_env["evidence_id"]],
            reason="evidence was associated with the wrong incident",
        )

    _assert_split_rollback_intact(correction_env)



@pytest.mark.parametrize(
    "fault_stage",
    [
        CorrectionStage.OLD_LINK_DEACTIVATED,
        CorrectionStage.EVIDENCE_UNLINKED_AUDIT_APPENDED,
        CorrectionStage.NEW_LINK_CREATED,
        CorrectionStage.EVIDENCE_LINKED_AUDIT_APPENDED,
    ],
)
def test_move_rolls_back_every_intermediate_stage(
    correction_env: dict[str, Any], fault_stage: CorrectionStage
) -> None:
    with pytest.raises(InjectedCorrectionFailure):
        _service(correction_env, fault_stage=fault_stage).move_evidence(
            source_incident_id=correction_env["source_incident_id"],
            evidence_id=correction_env["evidence_id"],
            target_incident_id=correction_env["target_incident_id"],
            reason="wrong incident association",
        )

    _assert_split_rollback_intact(correction_env)

def test_successful_split_is_atomic_and_preserves_source_evidence(
    correction_env: dict[str, Any],
) -> None:
    result = _service(correction_env).split_incident(
        source_incident_id=correction_env["source_incident_id"],
        evidence_ids=[correction_env["evidence_id"]],
        reason="separate mechanical incident",
    )

    assert result.source_incident_id == correction_env["source_incident_id"]
    assert result.evidence_ids == (correction_env["evidence_id"],)
    assert result.old_link_ids == (correction_env["old_link_id"],)
    assert len(result.new_link_ids) == 1

    with correction_env["factory"]() as session:
        evidence = session.get(EvidenceEventRecord, correction_env["evidence_id"])
        old_link = session.get(IncidentEvidenceLinkRecord, correction_env["old_link_id"])
        new_incident = session.get(IncidentRecord, result.new_incident_id)
        new_link = session.get(IncidentEvidenceLinkRecord, result.new_link_ids[0])

        assert evidence is not None
        assert old_link is not None and old_link.is_active is False
        assert old_link.unlinked_at is not None
        assert new_incident is not None
        assert new_incident.status == IncidentStatus.OPEN
        assert new_incident.machine_id == correction_env["machine_id"]
        assert new_link is not None
        assert new_link.is_active is True
        assert new_link.incident_id == result.new_incident_id
        assert new_link.evidence_event_id == correction_env["evidence_id"]
        assert new_link.relationship_type == old_link.relationship_type
        assert new_link.deterministic_rule_identifier == "test.correction.v1"

        source_actions = session.scalars(
            select(IncidentAuditEventRecord.action).where(
                IncidentAuditEventRecord.incident_id
                == correction_env["source_incident_id"]
            )
        ).all()
        target_actions = session.scalars(
            select(IncidentAuditEventRecord.action).where(
                IncidentAuditEventRecord.incident_id == result.new_incident_id
            )
        ).all()

        assert set(source_actions) == {
            IncidentAuditAction.EVIDENCE_UNLINKED,
            IncidentAuditAction.INCIDENT_SPLIT,
        }
        assert set(target_actions) == {
            IncidentAuditAction.INCIDENT_CREATED,
            IncidentAuditAction.EVIDENCE_LINKED,
        }


def test_move_evidence_to_existing_incident_preserves_inactive_history(
    correction_env: dict[str, Any],
) -> None:
    result = _service(correction_env).move_evidence(
        source_incident_id=correction_env["source_incident_id"],
        evidence_id=correction_env["evidence_id"],
        target_incident_id=correction_env["target_incident_id"],
        reason="operator selected the correct existing incident",
    )

    with correction_env["factory"]() as session:
        old_link = session.get(IncidentEvidenceLinkRecord, result.old_link_id)
        new_link = session.get(IncidentEvidenceLinkRecord, result.new_link_id)
        evidence = session.get(EvidenceEventRecord, correction_env["evidence_id"])
        assert evidence is not None
        assert old_link is not None and old_link.is_active is False
        assert new_link is not None and new_link.is_active is True
        assert new_link.incident_id == correction_env["target_incident_id"]
        assert _count(correction_env["factory"], IncidentRecord) == 2

        actions = session.scalars(
            select(IncidentAuditEventRecord.action).order_by(
                IncidentAuditEventRecord.occurred_at,
                IncidentAuditEventRecord.id,
            )
        ).all()
        assert set(actions) == {
            IncidentAuditAction.EVIDENCE_UNLINKED,
            IncidentAuditAction.EVIDENCE_LINKED,
        }
        assert IncidentAuditAction.INCIDENT_SPLIT not in actions


def test_controlled_split_api(correction_env: dict[str, Any]) -> None:
    response = correction_env["client"].post(
        f"/api/v1/incidents/{correction_env['source_incident_id']}/split",
        json={
            "evidence_ids": [str(correction_env["evidence_id"])],
            "reason": "split via controlled API",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_incident_id"] == str(correction_env["source_incident_id"])
    assert payload["evidence_ids"] == [str(correction_env["evidence_id"])]

    with correction_env["factory"]() as session:
        old_link = session.get(IncidentEvidenceLinkRecord, correction_env["old_link_id"])
        assert old_link is not None and old_link.is_active is False
        new_links = session.scalars(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.evidence_event_id
                == correction_env["evidence_id"],
                IncidentEvidenceLinkRecord.is_active.is_(True),
            )
        ).all()
        assert len(new_links) == 1
        assert str(new_links[0].incident_id) == payload["new_incident_id"]


def test_controlled_move_api(correction_env: dict[str, Any]) -> None:
    response = correction_env["client"].post(
        f"/api/v1/incidents/{correction_env['source_incident_id']}"
        f"/evidence/{correction_env['evidence_id']}/move",
        json={
            "target_incident_id": str(correction_env["target_incident_id"]),
            "reason": "move via controlled API",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_incident_id"] == str(correction_env["target_incident_id"])
    assert payload["evidence_id"] == str(correction_env["evidence_id"])
