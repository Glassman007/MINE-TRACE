from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from app.contracts.artifacts import generated_contract_documents
from app.contracts.versioning import (
    CURRENT_TRANSPORT_SCHEMA_VERSION,
    UnsupportedSchemaMajorError,
    ensure_supported_major,
    parse_schema_version,
)
from app.domain.enums import OperatingSessionState, SessionReportAcknowledgementState
from app.schemas.session_reports import (
    EvidenceManifest,
    MachineSessionReport,
    SessionOperatingSummary,
    SessionReportSyncMetadata,
)
from app.schemas.sync import (
    IncidentUpdate,
    SyncAcknowledgement,
    SyncAcknowledgementStatus,
    SyncEnvelope,
)

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contracts"
CHECKSUM = "sha256:" + "a" * 64


def _sample_report() -> MachineSessionReport:
    machine_id = uuid4()
    session_id = uuid4()
    generated_at = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    return MachineSessionReport(
        report_id=uuid4(),
        machine_id=machine_id,
        session_id=session_id,
        schema_version=CURRENT_TRANSPORT_SCHEMA_VERSION,
        generated_at=generated_at,
        operating_summary=SessionOperatingSummary(
            start=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
            end=generated_at,
            operating_hours=3.5,
            session_state=OperatingSessionState.CLOSED,
        ),
        incident_summaries=[],
        maintenance_actions=[],
        verification_results=[],
        unresolved_work=[],
        evidence_manifest=EvidenceManifest(
            schema_version=CURRENT_TRANSPORT_SCHEMA_VERSION,
            entries=[],
        ),
        sync_metadata=SessionReportSyncMetadata(
            local_revision=2,
            report_revision=1,
            acknowledgement_state=SessionReportAcknowledgementState.NOT_ACKNOWLEDGED,
        ),
        checksum=CHECKSUM,
    )


def _sample_envelope() -> SyncEnvelope:
    report = _sample_report()
    return SyncEnvelope(
        schema_version=CURRENT_TRANSPORT_SCHEMA_VERSION,
        package_id=uuid4(),
        source_machine_id=report.machine_id,
        source_node_id="edge-node-test",
        session_id=report.session_id,
        local_revision=report.sync_metadata.local_revision,
        report_revision=report.sync_metadata.report_revision,
        created_at=report.generated_at,
        machine_session_report=report,
        incident_updates=[],
        evidence_manifest=report.evidence_manifest,
        important_text_evidence=[],
        policy_selected_raw_evidence=[],
        checksum=CHECKSUM,
    )


def test_version_strategy_parses_major_minor_and_rejects_other_major() -> None:
    parsed = parse_schema_version("1.7")
    assert parsed.major == 1
    assert parsed.minor == 7
    assert str(parsed) == "1.7"
    ensure_supported_major("1.999")
    with pytest.raises(UnsupportedSchemaMajorError):
        ensure_supported_major("2.0")


def test_contract_artifacts_are_generated_from_current_models_without_drift() -> None:
    generated = generated_contract_documents()
    for filename, expected in generated.items():
        checked_in = json.loads((CONTRACT_DIR / filename).read_text(encoding="utf-8"))
        assert checked_in == expected, f"contract artifact drift: {filename}"


def test_all_checked_in_json_schemas_are_valid_draft_2020_12_schemas() -> None:
    for path in CONTRACT_DIR.glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(document)


def test_language_neutral_schemas_validate_serialized_backend_models() -> None:
    report = _sample_report()
    envelope = _sample_envelope()
    acknowledgement = SyncAcknowledgement(
        schema_version=CURRENT_TRANSPORT_SCHEMA_VERSION,
        package_id=envelope.package_id,
        status=SyncAcknowledgementStatus.ACKNOWLEDGED,
        central_revision=3,
        acknowledged_at=datetime(2026, 10, 3, 12, 1, tzinfo=timezone.utc),
    )
    incident = IncidentUpdate(
        schema_version=CURRENT_TRANSPORT_SCHEMA_VERSION,
        incident_id=uuid4(),
        machine_id=report.machine_id,
        state="OPEN",
        occurrence_count=1,
        report_revision=1,
    )
    cases = {
        "machine-session-report.schema.json": report.model_dump(mode="json"),
        "evidence-manifest.schema.json": report.evidence_manifest.model_dump(mode="json"),
        "incident-update.schema.json": incident.model_dump(mode="json"),
        "sync-envelope.schema.json": envelope.model_dump(mode="json"),
        "sync-acknowledgement.schema.json": acknowledgement.model_dump(mode="json"),
    }
    for filename, instance in cases.items():
        schema = json.loads((CONTRACT_DIR / filename).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(instance)


def test_envelope_rejects_nested_schema_version_drift() -> None:
    report = _sample_report()
    with pytest.raises(ValueError, match="evidence_manifest.schema_version"):
        SyncEnvelope(
            schema_version="1.0",
            package_id=uuid4(),
            source_machine_id=report.machine_id,
            session_id=report.session_id,
            local_revision=2,
            report_revision=1,
            created_at=report.generated_at,
            machine_session_report=report,
            incident_updates=[],
            evidence_manifest=EvidenceManifest(schema_version="1.1", entries=[]),
            checksum=CHECKSUM,
        )
