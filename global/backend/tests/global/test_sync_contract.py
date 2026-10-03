from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.edge import EdgeAuthenticationError, HashedBearerEdgeAuthenticator, hash_edge_token
from app.contracts.sync import (
    CURRENT_SYNC_SCHEMA_VERSION,
    ChecksumMismatchError,
    SyncAcknowledgement,
    SyncAcknowledgementStatus,
    UnsupportedSchemaVersionError,
    compute_revision_fingerprint,
    parse_sync_envelope,
    validate_envelope_checksum,
)
from app.contracts.sync_policy import RevisionDisposition, RevisionState, decide_revision
from tests.sync_test_data import ZERO_CHECKSUM, signed_envelope, signed_payload


def test_valid_envelope_and_checksum_round_trip() -> None:
    envelope = signed_envelope()
    validate_envelope_checksum(envelope)
    assert envelope.schema_version == CURRENT_SYNC_SCHEMA_VERSION
    assert envelope.machine_session_report.session.session_id == envelope.session_id


def test_unsupported_major_is_rejected_before_business_fields() -> None:
    payload = {"schema_version": "2.0.0", "not_a_business_contract": object()}
    with pytest.raises(UnsupportedSchemaVersionError):
        parse_sync_envelope(payload)


def test_malformed_identity_is_rejected() -> None:
    payload = signed_payload()
    payload["machine_session_report"]["session"]["machine_id"] = str(uuid4())
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    with pytest.raises(ValidationError, match="session machine identity"):
        parse_sync_envelope(payload)


def test_checksum_mismatch_is_rejected() -> None:
    envelope = signed_envelope()
    tampered = envelope.model_copy(
        update={
            "machine_session_report": envelope.machine_session_report.model_copy(
                update={
                    "machine": envelope.machine_session_report.machine.model_copy(
                        update={"display_name": "tampered"}
                    )
                }
            )
        }
    )
    with pytest.raises(ChecksumMismatchError):
        validate_envelope_checksum(tampered)


def test_revision_fingerprint_ignores_package_transport_identity_only() -> None:
    first = signed_envelope()
    payload = first.model_dump(mode="json")
    payload["package_id"] = str(uuid4())
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    second_unsigned = parse_sync_envelope(payload)
    assert compute_revision_fingerprint(first) == compute_revision_fingerprint(second_unsigned)


def test_revision_policy_is_explicit_and_deterministic() -> None:
    base = dict(
        incoming_revision=3,
        incoming_checksum="sha256:" + "1" * 64,
        incoming_fingerprint="sha256:" + "2" * 64,
    )
    assert decide_revision(RevisionState(**base, package_id_existing_checksum=base["incoming_checksum"])).disposition is RevisionDisposition.EXACT_REDELIVERY
    assert decide_revision(RevisionState(**base, package_id_existing_checksum="sha256:" + "3" * 64)).disposition is RevisionDisposition.PACKAGE_ID_REUSE_CONFLICT
    assert decide_revision(RevisionState(**base, logical_revision_existing_fingerprint=base["incoming_fingerprint"])).disposition is RevisionDisposition.LOGICAL_DUPLICATE
    assert decide_revision(RevisionState(**base, logical_revision_existing_fingerprint="sha256:" + "4" * 64)).disposition is RevisionDisposition.SAME_REVISION_CONFLICT
    older = {**base, "incoming_revision": 2}
    assert decide_revision(RevisionState(**older, latest_accepted_revision=3)).disposition is RevisionDisposition.OUT_OF_ORDER_CONFLICT
    assert decide_revision(RevisionState(**base, latest_accepted_revision=2)).disposition is RevisionDisposition.ACCEPT


def test_hashed_bearer_auth_rejects_node_token_mismatch() -> None:
    machine_a = uuid4()
    machine_b = uuid4()
    auth = HashedBearerEdgeAuthenticator(
        {
            str(machine_a): hash_edge_token("secret-a"),
            str(machine_b): hash_edge_token("secret-b"),
        }
    )
    principal = auth.authenticate(node_id=str(machine_a), authorization="Bearer secret-a")
    assert principal.machine_id == machine_a
    with pytest.raises(EdgeAuthenticationError):
        auth.authenticate(node_id=str(machine_a), authorization="Bearer secret-b")


def test_acknowledgement_schema() -> None:
    now = datetime.now(timezone.utc)
    ack = SyncAcknowledgement(
        schema_version="1.0.0",
        acknowledgement_id=uuid4(),
        package_id=uuid4(),
        source_machine_id=uuid4(),
        session_id=uuid4(),
        report_revision=1,
        status=SyncAcknowledgementStatus.ACCEPTED,
        received_at=now,
    )
    assert ack.model_dump(mode="json")["status"] == "ACCEPTED"


def test_generated_json_schemas_are_exact_snapshots_of_runtime_models() -> None:
    import json
    from pathlib import Path
    from app.contracts.sync import EvidenceManifest, IncidentUpdate, MachineSessionReport, SyncAcknowledgement, SyncEnvelope

    root = Path(__file__).resolve().parents[2]
    models = {
        "machine-session-report.schema.json": MachineSessionReport,
        "evidence-manifest.schema.json": EvidenceManifest,
        "incident-update.schema.json": IncidentUpdate,
        "sync-envelope.schema.json": SyncEnvelope,
        "sync-acknowledgement.schema.json": SyncAcknowledgement,
    }
    schema_dir = root / "shared" / "schema"
    assert set(models) == {path.name for path in schema_dir.glob("*.json")}
    for filename, model in models.items():
        generated = model.model_json_schema(ref_template="#/$defs/{model}")
        generated["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        generated["x-mine-trace-schema-version"] = CURRENT_SYNC_SCHEMA_VERSION
        persisted = json.loads((schema_dir / filename).read_text())
        assert persisted == generated


def test_checksum_reference_vector_is_locked_for_cross_language_producers() -> None:
    from uuid import UUID
    from app.contracts.sync import compute_envelope_checksum, parse_sync_envelope
    from tests.sync_test_data import envelope_payload

    envelope = parse_sync_envelope(
        envelope_payload(
            machine_id=UUID("11111111-1111-1111-1111-111111111111"),
            session_id=UUID("22222222-2222-2222-2222-222222222222"),
            package_id=UUID("33333333-3333-3333-3333-333333333333"),
            report_id=UUID("44444444-4444-4444-4444-444444444444"),
            component_id=UUID("55555555-5555-5555-5555-555555555555"),
            incident_id=UUID("66666666-6666-6666-6666-666666666666"),
            evidence_id=UUID("77777777-7777-7777-7777-777777777777"),
            action_id=UUID("88888888-8888-8888-8888-888888888888"),
            verification_id=UUID("99999999-9999-9999-9999-999999999999"),
        )
    )
    assert compute_envelope_checksum(envelope) == "sha256:b707ead0358f4ec56e3d8d6d1066c4fd937167946ffd3d3966696589c23cbbd6"
