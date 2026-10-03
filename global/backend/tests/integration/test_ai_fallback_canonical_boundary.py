from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.domain.enums import IncidentEvidenceRelationshipType, IncidentStatus
from app.integrations.llm import build_ai_provider
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationRunRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.services.ai_analysis_pipeline import AIAnalysisPipeline
from app.services.evidence_bundle import EvidenceBundleService


def test_deterministic_fallback_changes_zero_canonical_state(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        ai_enabled=False,
    )
    engine = create_sqlite_test_engine(tmp_path / 'fallback-boundary.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    machine_id = uuid4()
    incident_id = uuid4()
    evidence_id = uuid4()
    occurred = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.OPEN))
        session.flush()
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=None,
                source_type="HUMAN_OBSERVATION",
                original_source_record_id="fallback-boundary-1",
                original_timestamp=occurred,
                ingestion_timestamp=occurred,
                canonical_event_type="OPERATOR_OBSERVATION",
                canonical_payload={"note": "Hydraulic whine observed."},
                raw_source_payload={"note": "Hydraulic whine observed."},
                provenance={"source_system": "test"},
            )
        )
        session.flush()
        session.add(
            IncidentEvidenceLinkRecord(
                id=uuid4(),
                incident_id=incident_id,
                evidence_event_id=evidence_id,
                is_active=True,
                relationship_type=IncidentEvidenceRelationshipType.RELATED,
                deterministic_rule_identifier="test.rule",
                link_reason="test",
                linked_at=occurred,
            )
        )

    def snapshot() -> tuple[object, ...]:
        with factory() as session:
            incident = session.get(IncidentRecord, incident_id)
            evidence = session.get(EvidenceEventRecord, evidence_id)
            links = session.scalars(
                select(IncidentEvidenceLinkRecord).where(
                    IncidentEvidenceLinkRecord.incident_id == incident_id
                )
            ).all()
            assert incident is not None and evidence is not None
            return (
                incident.status,
                incident.owner_ref,
                incident.severity,
                evidence.id,
                evidence.machine_id,
                evidence.component_id,
                evidence.canonical_payload.copy(),
                evidence.provenance.copy(),
                tuple((link.id, link.is_active, link.relationship_type) for link in links),
                session.scalar(select(func.count()).select_from(IncidentAuditEventRecord)),
                session.scalar(select(func.count()).select_from(VerificationRunRecord)),
            )

    before = snapshot()
    bundle = EvidenceBundleService(
        lambda: SQLAlchemyUnitOfWork(factory),
        settings,
    ).build(incident_id)
    result = AIAnalysisPipeline(build_ai_provider(settings)).analyze(bundle)
    after = snapshot()

    assert result.result_type.value == "FALLBACK"
    assert before == after
    engine.dispose()
