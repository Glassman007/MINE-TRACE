from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.domain.enums import IncidentStatus, VerificationRunResult
from app.models import (
    ContextSnapshotRecord,
    EvidenceAttachmentRecord,
    EvidenceEventRecord,
    HandoverItemRecord,
    HandoverPacketRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationEvidenceRecord,
    VerificationRunRecord,
)
from app.seed import (
    EVIDENCE_IDS,
    HANDOVER_IDS,
    INCIDENT_IDS,
    MACHINE_IDS,
    VERIFICATION_IDS,
    SeedError,
    seed_database,
)


ANCHOR = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _settings(tmp_path, *, environment="test") -> Settings:
    return Settings(
        environment=environment,
        database_url=f"sqlite:///{tmp_path / 'seed.db'}",
        sqlite_wal_enabled=False,
    )


def _prepare(settings: Settings) -> None:
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    engine.dispose()


def _session(settings: Settings):
    engine = create_database_engine(settings)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    return engine, factory()


def test_seed_builds_meaningful_scenario_and_validates_invariants(tmp_path):
    settings = _settings(tmp_path)
    _prepare(settings)

    summary = seed_database(settings, reset=True, anchor=ANCHOR)

    assert summary.anchor == ANCHOR.isoformat()
    assert summary.validation["foreign_keys"] == "ok"
    assert summary.validation["source_identity_uniqueness"] == "ok"
    assert summary.validation["occurrence_reconstruction"]["count"] == 2
    assert summary.semantic_demo["candidate_label"] == "SIMILAR_SEMANTIC_HISTORY_CANDIDATE"

    engine, session = _session(settings)
    try:
        assert set(session.scalars(select(MachineRecord.id)).all()) >= set(MACHINE_IDS.values())

        source_types = set(session.scalars(select(EvidenceEventRecord.source_type)).all())
        assert {"MACHINE_EVENT", "MAINTENANCE_RECORD", "HUMAN_OBSERVATION"} <= source_types

        assert session.scalar(select(func.count(ContextSnapshotRecord.id))) >= len(EVIDENCE_IDS)

        audio = session.scalar(
            select(EvidenceAttachmentRecord).where(
                EvidenceAttachmentRecord.evidence_event_id == EVIDENCE_IDS["operator_audio"]
            )
        )
        assert audio is not None
        assert audio.attachment_type == "AUDIO"
        assert audio.mime_type == "audio/wav"
        assert audio.checksum

        hydraulic = session.get(IncidentRecord, INCIDENT_IDS["hydraulic_open_with_recurrence"])
        verifying = session.get(IncidentRecord, INCIDENT_IDS["brake_verifying"])
        verified = session.get(IncidentRecord, INCIDENT_IDS["cooling_verified"])
        recurred = session.get(IncidentRecord, INCIDENT_IDS["excavator_recurred"])
        assert hydraulic is not None and hydraulic.status == IncidentStatus.OPEN
        assert verifying is not None and verifying.status == IncidentStatus.VERIFYING
        assert verified is not None and verified.status == IncidentStatus.VERIFIED
        assert recurred is not None and recurred.status == IncidentStatus.RECURRED

        recurrence_links = session.scalars(
            select(IncidentEvidenceLinkRecord).where(
                IncidentEvidenceLinkRecord.incident_id
                == INCIDENT_IDS["hydraulic_open_with_recurrence"]
            )
        ).all()
        assert len(recurrence_links) == 2

        pending = session.get(VerificationRunRecord, VERIFICATION_IDS["brake_pending"])
        succeeded = session.get(VerificationRunRecord, VERIFICATION_IDS["cooling_succeeded"])
        failed = session.get(
            VerificationRunRecord, VERIFICATION_IDS["excavator_recurrence_detected"]
        )
        assert pending is not None and pending.completed_at is None
        assert succeeded is not None and succeeded.result == VerificationRunResult.SUCCEEDED
        assert failed is not None and failed.result == VerificationRunResult.RECURRENCE_DETECTED
        assert session.scalar(
            select(func.count(VerificationEvidenceRecord.id)).where(
                VerificationEvidenceRecord.verification_run_id == failed.id
            )
        ) == 1

        assert session.get(HandoverPacketRecord, HANDOVER_IDS["historical_acknowledged"]) is not None
        assert session.get(HandoverPacketRecord, HANDOVER_IDS["current_unacknowledged"]) is not None

        historical_item = session.scalar(
            select(HandoverItemRecord).where(
                HandoverItemRecord.handover_packet_id == HANDOVER_IDS["historical_acknowledged"],
                HandoverItemRecord.incident_id == INCIDENT_IDS["excavator_recurred"],
            )
        )
        assert historical_item is not None
        assert historical_item.status_snapshot == IncidentStatus.VERIFYING
        assert recurred.status == IncidentStatus.RECURRED

        semantic = session.get(EvidenceEventRecord, EVIDENCE_IDS["hydraulic_semantic_history"])
        assert semantic is not None
        assert semantic.provenance["semantic_demo"]["candidate_for_evidence_id"] == str(
            EVIDENCE_IDS["hydraulic_initial"]
        )

        assert session.scalar(select(func.count(IncidentAuditEventRecord.id))) > 0
    finally:
        session.close()
        engine.dispose()


def test_seed_is_idempotent_without_reset(tmp_path):
    settings = _settings(tmp_path)
    _prepare(settings)

    first = seed_database(settings, reset=True, anchor=ANCHOR)
    second = seed_database(
        settings,
        reset=False,
        anchor=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    assert second.anchor == first.anchor
    engine, session = _session(settings)
    try:
        assert session.scalar(select(func.count(EvidenceEventRecord.id))) == len(EVIDENCE_IDS)
        assert session.scalar(select(func.count(IncidentRecord.id))) == len(INCIDENT_IDS)
    finally:
        session.close()
        engine.dispose()


def test_reset_reseeds_same_stable_ids_at_new_anchor(tmp_path):
    settings = _settings(tmp_path)
    _prepare(settings)
    seed_database(settings, reset=True, anchor=ANCHOR)

    later = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    summary = seed_database(settings, reset=True, anchor=later)
    assert summary.anchor == later.isoformat()

    engine, session = _session(settings)
    try:
        evidence = session.get(EvidenceEventRecord, EVIDENCE_IDS["hydraulic_initial"])
        assert evidence is not None
        assert evidence.id == EVIDENCE_IDS["hydraulic_initial"]
        # SQLite returns a naive datetime; value still reflects the new UTC anchor.
        assert evidence.original_timestamp.replace(tzinfo=timezone.utc) == later.replace(
            tzinfo=None
        ).replace(tzinfo=timezone.utc) - __import__("datetime").timedelta(minutes=30)
    finally:
        session.close()
        engine.dispose()


def test_seed_refuses_production_environment(tmp_path):
    settings = _settings(tmp_path, environment="production")
    _prepare(settings)
    with pytest.raises(SeedError, match="disabled outside development/test"):
        seed_database(settings, reset=True, anchor=ANCHOR)
