from __future__ import annotations

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.errors import install_exception_handlers
from app.api.sync import get_edge_authenticator, router as sync_router
from app.auth.edge import HashedBearerEdgeAuthenticator, hash_edge_token
from app.contracts.sync import (
    SyncAcknowledgementStatus,
    parse_sync_envelope,
    with_computed_checksum,
)
from app.db.base import Base
from app.db.session import get_db_session
from app.models import (
    EvidenceEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    IncidentSessionLinkRecord,
    MachineRecord,
    MaintenanceActionRecord,
    OperatingSessionRecord,
    SessionReportRecord,
    SyncConflictRecord,
    SyncReceiptRecord,
    VerificationRunRecord,
)
from app.services.sync_ingestion import GlobalSyncIngestionService
from tests.sync_test_data import ZERO_CHECKSUM, envelope_payload, signed_envelope, signed_payload


@pytest.fixture
def db_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_successful_package_persists_explicit_canonical_relationships(db_factory) -> None:
    envelope = signed_envelope()
    evidence_id = envelope.evidence_manifest.entries[0].evidence_id
    incident_id = envelope.incident_updates[0].incident_id

    with db_factory() as session:
        result = GlobalSyncIngestionService(session).ingest(envelope)
        assert result.acknowledgement.status is SyncAcknowledgementStatus.ACCEPTED
        assert result.semantic_evidence_ids == (evidence_id,)

    with db_factory() as session:
        assert _count(session, MachineRecord) == 1
        assert _count(session, OperatingSessionRecord) == 1
        assert _count(session, IncidentRecord) == 1
        assert _count(session, EvidenceEventRecord) == 1
        assert _count(session, IncidentSessionLinkRecord) == 1
        assert _count(session, IncidentEvidenceLinkRecord) == 1
        assert _count(session, MaintenanceActionRecord) == 1
        assert _count(session, VerificationRunRecord) == 1
        assert _count(session, SessionReportRecord) == 1
        assert _count(session, SyncReceiptRecord) == 1
        evidence = session.get(EvidenceEventRecord, evidence_id)
        assert evidence is not None and evidence.id == evidence_id
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None and incident.machine_id == envelope.source_machine_id


def test_exact_duplicate_package_returns_previous_ack_without_duplication(db_factory) -> None:
    envelope = signed_envelope()
    with db_factory() as session:
        first = GlobalSyncIngestionService(session).ingest(envelope)
    with db_factory() as session:
        second = GlobalSyncIngestionService(session).ingest(envelope)
        assert second.acknowledgement == first.acknowledgement
        assert _count(session, EvidenceEventRecord) == 1
        assert _count(session, SessionReportRecord) == 1
        assert _count(session, SyncReceiptRecord) == 1


def test_same_logical_revision_new_package_is_duplicate_receipt_only(db_factory) -> None:
    first = signed_envelope()
    second = first.model_copy(update={"package_id": uuid4()})
    second = with_computed_checksum(second)

    with db_factory() as session:
        accepted = GlobalSyncIngestionService(session).ingest(first)
    with db_factory() as session:
        duplicate = GlobalSyncIngestionService(session).ingest(second)
        assert accepted.acknowledgement.status is SyncAcknowledgementStatus.ACCEPTED
        assert duplicate.acknowledgement.status is SyncAcknowledgementStatus.DUPLICATE
        assert duplicate.acknowledgement.canonical_receipt_id == accepted.acknowledgement.acknowledgement_id
        assert _count(session, SessionReportRecord) == 1
        assert _count(session, EvidenceEventRecord) == 1
        assert _count(session, SyncReceiptRecord) == 2


def test_newer_revision_preserves_prior_report_and_deduplicates_stable_records(db_factory) -> None:
    machine_id = uuid4()
    session_id = uuid4()
    component_id = uuid4()
    incident_id = uuid4()
    evidence_id = uuid4()
    action_id = uuid4()
    verification_id = uuid4()
    common = dict(
        machine_id=machine_id,
        session_id=session_id,
        component_id=component_id,
        incident_id=incident_id,
        evidence_id=evidence_id,
        action_id=action_id,
        verification_id=verification_id,
    )
    revision_1 = signed_envelope(report_revision=1, **common)
    revision_2 = signed_envelope(report_revision=2, **common)

    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(revision_1)
    with db_factory() as session:
        result = GlobalSyncIngestionService(session).ingest(revision_2)
        assert result.acknowledgement.status is SyncAcknowledgementStatus.ACCEPTED
        reports = tuple(
            session.scalars(
                select(SessionReportRecord)
                .where(SessionReportRecord.session_id == session_id)
                .order_by(SessionReportRecord.report_revision)
            )
        )
        assert [item.report_revision for item in reports] == [1, 2]
        assert _count(session, EvidenceEventRecord) == 1
        assert _count(session, MaintenanceActionRecord) == 1
        assert _count(session, VerificationRunRecord) == 1
        assert _count(session, IncidentSessionLinkRecord) == 1
        assert _count(session, IncidentEvidenceLinkRecord) == 1
        operating_session = session.get(OperatingSessionRecord, session_id)
        assert operating_session is not None and operating_session.latest_report_revision == 2


def test_conflicting_same_revision_creates_conflict_and_preserves_accepted_state(db_factory) -> None:
    first = signed_envelope()
    payload = first.model_dump(mode="json")
    payload["package_id"] = str(uuid4())
    payload["machine_session_report"]["machine"]["display_name"] = "Incompatible replacement"
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    conflicting = with_computed_checksum(parse_sync_envelope(payload))

    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(first)
    with db_factory() as session:
        result = GlobalSyncIngestionService(session).ingest(conflicting)
        assert result.acknowledgement.status is SyncAcknowledgementStatus.CONFLICT
        assert _count(session, SyncConflictRecord) == 1
        assert _count(session, SessionReportRecord) == 1
        assert _count(session, SyncReceiptRecord) == 2
        machine = session.get(MachineRecord, first.source_machine_id)
        assert machine is not None and machine.display_name == "Haul Truck"
        conflict = session.scalar(select(SyncConflictRecord))
        assert conflict is not None and conflict.conflict_type == "SAME_REVISION_CONTENT_MISMATCH"


def test_unseen_older_revision_cannot_overwrite_newer_accepted_revision(db_factory) -> None:
    machine_id = uuid4()
    session_id = uuid4()
    common = dict(machine_id=machine_id, session_id=session_id)
    newer = signed_envelope(report_revision=2, **common)
    older = signed_envelope(report_revision=1, **common)

    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(newer)
    with db_factory() as session:
        result = GlobalSyncIngestionService(session).ingest(older)
        assert result.acknowledgement.status is SyncAcknowledgementStatus.CONFLICT
        assert _count(session, SessionReportRecord) == 1
        operating_session = session.get(OperatingSessionRecord, session_id)
        assert operating_session is not None and operating_session.latest_report_revision == 2
        conflict = session.scalar(select(SyncConflictRecord))
        assert conflict is not None and conflict.conflict_type == "OUT_OF_ORDER_REVISION"


def test_duplicate_evidence_in_newer_revision_is_not_reinserted(db_factory) -> None:
    machine_id = uuid4()
    session_id = uuid4()
    evidence_id = uuid4()
    incident_id = uuid4()
    component_id = uuid4()
    action_id = uuid4()
    verification_id = uuid4()
    common = dict(
        machine_id=machine_id,
        session_id=session_id,
        evidence_id=evidence_id,
        incident_id=incident_id,
        component_id=component_id,
        action_id=action_id,
        verification_id=verification_id,
    )
    first = signed_envelope(report_revision=1, **common)
    second = signed_envelope(report_revision=2, **common)
    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(first)
    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(second)
        assert _count(session, EvidenceEventRecord) == 1


def test_100_machine_bulk_routes_by_explicit_ids_without_ai_categorization(db_factory) -> None:
    identities: list[tuple[UUID, UUID, UUID]] = []
    for _ in range(100):
        envelope = signed_envelope()
        identities.append(
            (
                envelope.source_machine_id,
                envelope.session_id,
                envelope.evidence_manifest.entries[0].evidence_id,
            )
        )
        with db_factory() as session:
            result = GlobalSyncIngestionService(session).ingest(envelope)
            assert result.acknowledgement.status is SyncAcknowledgementStatus.ACCEPTED

    with db_factory() as session:
        assert _count(session, MachineRecord) == 100
        assert _count(session, OperatingSessionRecord) == 100
        assert _count(session, EvidenceEventRecord) == 100
        for machine_id, session_id, evidence_id in identities:
            session_row = session.get(OperatingSessionRecord, session_id)
            evidence = session.get(EvidenceEventRecord, evidence_id)
            assert session_row is not None and session_row.machine_id == machine_id
            assert evidence is not None and evidence.machine_id == machine_id
            assert evidence.session_id == session_id


def test_package_id_reuse_with_changed_checksum_is_explicit_and_idempotent(db_factory) -> None:
    first = signed_envelope()
    payload = first.model_dump(mode="json")
    payload["machine_session_report"]["machine"]["display_name"] = "changed package reuse"
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    reused = with_computed_checksum(parse_sync_envelope(payload))

    with db_factory() as session:
        accepted = GlobalSyncIngestionService(session).ingest(first)
    with db_factory() as session:
        conflict_1 = GlobalSyncIngestionService(session).ingest(reused)
    with db_factory() as session:
        conflict_2 = GlobalSyncIngestionService(session).ingest(reused)
        assert conflict_1.acknowledgement == conflict_2.acknowledgement
        assert conflict_1.acknowledgement.status is SyncAcknowledgementStatus.CONFLICT
        assert conflict_1.acknowledgement.canonical_receipt_id == accepted.acknowledgement.acknowledgement_id
        assert _count(session, SyncConflictRecord) == 1
        assert _count(session, SyncReceiptRecord) == 1
        assert _count(session, SessionReportRecord) == 1


def test_transaction_rolls_back_partial_projection_changes_on_canonical_error(db_factory) -> None:
    first = signed_envelope()
    payload = first.model_dump(mode="json")
    payload["package_id"] = str(uuid4())
    payload["report_revision"] = 2
    payload["machine_session_report"]["report_revision"] = 2
    payload["machine_session_report"]["machine"]["display_name"] = "must roll back"
    payload["evidence_manifest"]["entries"][0]["original_source_record_id"] = "incompatible-source-id"
    payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    invalid_newer = with_computed_checksum(parse_sync_envelope(payload))

    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(first)
    from app.services.sync_ingestion import SyncIngestionError
    with db_factory() as session:
        with pytest.raises(SyncIngestionError, match="evidence UUID"):
            GlobalSyncIngestionService(session).ingest(invalid_newer)
    with db_factory() as session:
        machine = session.get(MachineRecord, first.source_machine_id)
        operating_session = session.get(OperatingSessionRecord, first.session_id)
        assert machine is not None and machine.display_name == "Haul Truck"
        assert operating_session is not None and operating_session.latest_report_revision == 1
        assert _count(session, SessionReportRecord) == 1
        assert _count(session, SyncReceiptRecord) == 1


class CommitCheckingIndexer:
    def __init__(self, db_factory, evidence_id: UUID) -> None:
        self.db_factory = db_factory
        self.evidence_id = evidence_id
        self.saw_committed_row = False

    def batch_index(self, evidence_ids) -> None:
        assert tuple(evidence_ids) == (self.evidence_id,)
        with self.db_factory() as session:
            self.saw_committed_row = session.get(EvidenceEventRecord, self.evidence_id) is not None
        assert self.saw_committed_row


def test_semantic_dispatch_observes_committed_canonical_row(db_factory) -> None:
    payload = signed_payload()
    machine_id = UUID(payload["source_machine_id"])
    evidence_id = UUID(payload["evidence_manifest"]["entries"][0]["evidence_id"])
    indexer = CommitCheckingIndexer(db_factory, evidence_id)
    with _api_client(db_factory, machine_id, "edge-secret", indexer=indexer) as client:
        response = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert response.status_code == 200
    assert indexer.saw_committed_row is True


class RaisingIndexer:
    def __init__(self, message: str) -> None:
        self.message = message
        self.called = 0

    def batch_index(self, _evidence_ids) -> None:
        self.called += 1
        raise RuntimeError(self.message)


class ForbiddenAI:
    def __init__(self) -> None:
        self.called = False

    def __getattribute__(self, name):
        if name == "called":
            return object.__getattribute__(self, name)
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        object.__setattr__(self, "called", True)
        raise AssertionError("sync ingestion must not invoke AI")


def _api_client(db_factory, machine_id: UUID, token: str, *, indexer=None, ai=None) -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(sync_router, prefix="/api/v1")
    if indexer is not None:
        app.state.semantic_indexing_service = indexer
    if ai is not None:
        app.state.ai_service = ai

    def db_dependency():
        session = db_factory()
        try:
            yield session
        finally:
            session.close()

    auth = HashedBearerEdgeAuthenticator({str(machine_id): hash_edge_token(token)})
    app.dependency_overrides[get_db_session] = db_dependency
    app.dependency_overrides[get_edge_authenticator] = lambda: auth
    return TestClient(app)


def _headers(machine_id: UUID, token: str = "edge-secret") -> dict[str, str]:
    return {
        "X-Mine-Trace-Node-Id": str(machine_id),
        "Authorization": f"Bearer {token}",
    }


def test_invalid_checksum_is_rejected_before_database_write(db_factory) -> None:
    payload = signed_payload()
    machine_id = UUID(payload["source_machine_id"])
    payload["machine_session_report"]["machine"]["display_name"] = "tampered after signing"
    with _api_client(db_factory, machine_id, "edge-secret") as client:
        response = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SYNC_CHECKSUM_MISMATCH"
    with db_factory() as session:
        assert _count(session, SyncReceiptRecord) == 0
        assert _count(session, MachineRecord) == 0


def test_unsupported_schema_version_is_rejected_before_business_validation(db_factory) -> None:
    machine_id = uuid4()
    payload = {"schema_version": "2.0.0", "garbage": "not interpreted"}
    with _api_client(db_factory, machine_id, "edge-secret") as client:
        response = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_SYNC_SCHEMA_VERSION"


def test_wrong_node_authentication_wins_before_schema_or_business_validation(db_factory) -> None:
    registered = uuid4()
    wrong_node = uuid4()
    payload = {"schema_version": "2.0.0", "garbage": "invalid"}
    with _api_client(db_factory, registered, "edge-secret") as client:
        response = client.post(
            "/api/v1/sync/packages",
            json=payload,
            headers=_headers(wrong_node, token="edge-secret"),
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "EDGE_AUTHENTICATION_FAILED"


def test_authenticated_node_cannot_submit_another_machine(db_factory) -> None:
    registered = uuid4()
    payload = signed_payload(machine_id=uuid4())
    with _api_client(db_factory, registered, "edge-secret") as client:
        response = client.post(
            "/api/v1/sync/packages",
            json=payload,
            headers=_headers(registered),
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EDGE_NODE_MACHINE_MISMATCH"


@pytest.mark.parametrize("failure", ["qdrant unavailable", "embedding unavailable"])
def test_derived_semantic_failure_occurs_after_commit_and_does_not_roll_back(db_factory, failure) -> None:
    payload = signed_payload()
    machine_id = UUID(payload["source_machine_id"])
    indexer = RaisingIndexer(failure)
    with _api_client(db_factory, machine_id, "edge-secret", indexer=indexer) as client:
        response = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"
    assert indexer.called == 1
    with db_factory() as session:
        assert _count(session, SyncReceiptRecord) == 1
        assert _count(session, EvidenceEventRecord) == 1
        assert _count(session, SessionReportRecord) == 1


def test_ai_unavailable_is_outside_sync_transaction_and_canonical_ingestion_succeeds(db_factory) -> None:
    payload = signed_payload()
    machine_id = UUID(payload["source_machine_id"])
    ai = ForbiddenAI()
    with _api_client(db_factory, machine_id, "edge-secret", ai=ai) as client:
        response = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert response.status_code == 200
    assert ai.called is False
    with db_factory() as session:
        assert _count(session, SyncReceiptRecord) == 1
        assert _count(session, MachineRecord) == 1


def test_http_endpoint_exact_redelivery_returns_same_acknowledgement(db_factory) -> None:
    payload = signed_payload()
    machine_id = UUID(payload["source_machine_id"])
    with _api_client(db_factory, machine_id, "edge-secret") as client:
        first = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
        second = client.post("/api/v1/sync/packages", json=payload, headers=_headers(machine_id))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    with db_factory() as session:
        assert _count(session, SyncReceiptRecord) == 1
        assert _count(session, SessionReportRecord) == 1


def test_http_endpoint_same_revision_conflict_returns_409_ack(db_factory) -> None:
    accepted_payload = signed_payload()
    machine_id = UUID(accepted_payload["source_machine_id"])
    conflicting_payload = dict(accepted_payload)
    # deep copy through JSON-compatible structures
    import copy
    conflicting_payload = copy.deepcopy(accepted_payload)
    conflicting_payload["package_id"] = str(uuid4())
    conflicting_payload["machine_session_report"]["machine"]["display_name"] = "conflict over HTTP"
    conflicting_payload["sync_metadata"]["checksum"] = ZERO_CHECKSUM
    conflicting = with_computed_checksum(parse_sync_envelope(conflicting_payload)).model_dump(mode="json")

    with _api_client(db_factory, machine_id, "edge-secret") as client:
        accepted = client.post("/api/v1/sync/packages", json=accepted_payload, headers=_headers(machine_id))
        conflict = client.post("/api/v1/sync/packages", json=conflicting, headers=_headers(machine_id))
    assert accepted.status_code == 200
    assert conflict.status_code == 409
    body = conflict.json()
    assert body["status"] == "CONFLICT"
    assert body["conflict_id"] is not None
    with db_factory() as session:
        assert _count(session, SyncConflictRecord) == 1
        assert _count(session, SessionReportRecord) == 1


def test_policy_selected_raw_evidence_is_persisted_without_becoming_a_required_capability(db_factory) -> None:
    payload = envelope_payload()
    evidence_id = payload["evidence_manifest"]["entries"][0]["evidence_id"]
    attachment_id = str(uuid4())
    payload["optional_policy_selected_raw_evidence"] = [
        {
            "evidence_id": evidence_id,
            "attachment_id": attachment_id,
            "attachment_type": "IMAGE_REFERENCE",
            "storage_reference": "edge://evidence/image-1",
            "mime_type": "image/jpeg",
            "file_size": 1234,
            "checksum": "sha256:" + "a" * 64,
            "raw_payload": {"capture": "policy-selected"},
            "created_at": payload["sync_metadata"]["produced_at"],
        }
    ]
    envelope = with_computed_checksum(parse_sync_envelope(payload))
    from app.models import EvidenceAttachmentRecord
    with db_factory() as session:
        GlobalSyncIngestionService(session).ingest(envelope)
    with db_factory() as session:
        evidence = session.get(EvidenceEventRecord, UUID(evidence_id))
        attachment = session.get(EvidenceAttachmentRecord, UUID(attachment_id))
        assert evidence is not None and evidence.raw_source_payload == {"capture": "policy-selected"}
        assert attachment is not None and attachment.storage_reference == "edge://evidence/image-1"
