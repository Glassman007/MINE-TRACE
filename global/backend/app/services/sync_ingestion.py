from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.sync import (
    SyncAcknowledgement,
    SyncAcknowledgementStatus,
    SyncEnvelope,
    compute_revision_fingerprint,
)
from app.contracts.sync_policy import RevisionDisposition, RevisionState, decide_revision
from app.domain.enums import IncidentEvidenceRelationshipType, IncidentStatus, SemanticIndexOutboxStatus, VerificationRunResult
from app.models import (
    ComponentRecord,
    EvidenceAttachmentRecord,
    EvidenceEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    IncidentSessionLinkRecord,
    MachineRecord,
    MaintenanceActionRecord,
    OperatingSessionRecord,
    SemanticIndexOutboxRecord,
    SessionReportRecord,
    SyncConflictRecord,
    SyncReceiptRecord,
    VerificationEvidenceRecord,
    VerificationRunRecord,
)


class SyncIngestionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SyncIngestionResult:
    acknowledgement: SyncAcknowledgement
    semantic_evidence_ids: tuple[UUID, ...] = ()


class GlobalSyncIngestionService:
    """Transactional edge-package ingestion into canonical fleet PostgreSQL.

    This service never calls embeddings, Qdrant, or AI. It returns the selected
    evidence IDs that the transport layer may schedule for derived semantic
    indexing *after* this method's transaction has committed.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest(self, envelope: SyncEnvelope) -> SyncIngestionResult:
        revision_fingerprint = compute_revision_fingerprint(envelope)
        semantic_ids = tuple(item.evidence_id for item in envelope.important_text_evidence)
        now = datetime.now(timezone.utc)

        with self._session.begin():
            package_receipts = tuple(
                self._session.scalars(
                    select(SyncReceiptRecord)
                    .where(
                        SyncReceiptRecord.source_machine_id == envelope.source_machine_id,
                        SyncReceiptRecord.package_id == envelope.package_id,
                    )
                    .order_by(SyncReceiptRecord.received_at.asc(), SyncReceiptRecord.id.asc())
                )
            )
            exact_receipt = next(
                (item for item in package_receipts if item.checksum == envelope.sync_metadata.checksum),
                None,
            )
            package_existing_checksum = package_receipts[0].checksum if package_receipts else None

            # A package-id-reuse conflict cannot always create a second receipt
            # because the incoming payload may claim a session identity that is
            # not canonical. The conflict row itself is therefore also a durable
            # acknowledgement for exact redelivery of that incompatible attempt.
            prior_package_conflict = self._session.scalar(
                select(SyncConflictRecord)
                .where(
                    SyncConflictRecord.source_machine_id == envelope.source_machine_id,
                    SyncConflictRecord.incoming_package_id == envelope.package_id,
                    SyncConflictRecord.incoming_checksum == envelope.sync_metadata.checksum,
                )
                .order_by(SyncConflictRecord.detected_at.asc(), SyncConflictRecord.id.asc())
            )
            if exact_receipt is None and prior_package_conflict is not None:
                detected_at = prior_package_conflict.detected_at
                if detected_at.tzinfo is None:
                    detected_at = detected_at.replace(tzinfo=timezone.utc)
                return SyncIngestionResult(
                    acknowledgement=SyncAcknowledgement(
                        schema_version=envelope.schema_version,
                        acknowledgement_id=prior_package_conflict.id,
                        package_id=envelope.package_id,
                        source_machine_id=envelope.source_machine_id,
                        session_id=envelope.session_id,
                        report_revision=envelope.report_revision,
                        status=SyncAcknowledgementStatus.CONFLICT,
                        received_at=detected_at,
                        canonical_receipt_id=prior_package_conflict.existing_receipt_id,
                        conflict_id=prior_package_conflict.id,
                    )
                )

            existing_report = self._session.scalar(
                select(SessionReportRecord).where(
                    SessionReportRecord.source_machine_id == envelope.source_machine_id,
                    SessionReportRecord.session_id == envelope.session_id,
                    SessionReportRecord.report_revision == envelope.report_revision,
                )
            )
            latest_revision = self._session.scalar(
                select(func.max(SessionReportRecord.report_revision)).where(
                    SessionReportRecord.source_machine_id == envelope.source_machine_id,
                    SessionReportRecord.session_id == envelope.session_id,
                )
            )

            decision = decide_revision(
                RevisionState(
                    incoming_revision=envelope.report_revision,
                    incoming_checksum=envelope.sync_metadata.checksum,
                    incoming_fingerprint=revision_fingerprint,
                    package_id_existing_checksum=package_existing_checksum,
                    logical_revision_existing_fingerprint=(
                        existing_report.checksum if existing_report is not None else None
                    ),
                    latest_accepted_revision=latest_revision,
                )
            )

            if decision.disposition is RevisionDisposition.EXACT_REDELIVERY:
                if exact_receipt is None:
                    raise RuntimeError("revision policy found exact redelivery without its receipt")
                ack = self._acknowledgement_from_receipt(exact_receipt)
                return SyncIngestionResult(acknowledgement=ack)

            if decision.disposition is RevisionDisposition.PACKAGE_ID_REUSE_CONFLICT:
                existing_receipt = package_receipts[0]
                conflict = self._persist_conflict(
                    envelope=envelope,
                    existing_receipt=existing_receipt,
                    existing_report=existing_report,
                    conflict_type=decision.conflict_type or "PACKAGE_ID_REUSE",
                    revision_fingerprint=revision_fingerprint,
                    now=now,
                    session_id_for_fk=existing_receipt.session_id,
                )
                # The original package already owns the package receipt identity;
                # this incompatible reuse is durably represented by sync_conflicts.
                ack = SyncAcknowledgement(
                    schema_version=envelope.schema_version,
                    acknowledgement_id=conflict.id,
                    package_id=envelope.package_id,
                    source_machine_id=envelope.source_machine_id,
                    session_id=envelope.session_id,
                    report_revision=envelope.report_revision,
                    status=SyncAcknowledgementStatus.CONFLICT,
                    received_at=conflict.detected_at,
                    canonical_receipt_id=existing_receipt.id,
                    conflict_id=conflict.id,
                )
                return SyncIngestionResult(acknowledgement=ack)

            if decision.disposition is RevisionDisposition.LOGICAL_DUPLICATE:
                if existing_report is None:
                    raise RuntimeError("logical duplicate decision requires an existing report")
                canonical_receipt = self._find_accepted_receipt(
                    envelope.source_machine_id, envelope.session_id, envelope.report_revision
                )
                receipt = self._new_receipt(
                    envelope,
                    status=SyncAcknowledgementStatus.DUPLICATE,
                    now=now,
                )
                self._session.add(receipt)
                self._session.flush()
                ack = self._acknowledgement_from_receipt(
                    receipt,
                    canonical_receipt_id=(canonical_receipt.id if canonical_receipt else None),
                )
                return SyncIngestionResult(acknowledgement=ack)

            if decision.disposition in {
                RevisionDisposition.SAME_REVISION_CONFLICT,
                RevisionDisposition.OUT_OF_ORDER_CONFLICT,
            }:
                existing_receipt = self._find_accepted_receipt(
                    envelope.source_machine_id,
                    envelope.session_id,
                    envelope.report_revision,
                )
                if existing_receipt is None and latest_revision is not None:
                    existing_receipt = self._find_accepted_receipt(
                        envelope.source_machine_id,
                        envelope.session_id,
                        latest_revision,
                    )
                session = self._session.get(OperatingSessionRecord, envelope.session_id)
                if session is None:
                    raise SyncIngestionError(
                        "REVISION_CONFLICT_WITHOUT_SESSION",
                        "cannot persist revision conflict because the referenced canonical session does not exist",
                        status_code=409,
                    )
                conflict = self._persist_conflict(
                    envelope=envelope,
                    existing_receipt=existing_receipt,
                    existing_report=existing_report,
                    conflict_type=decision.conflict_type or "REVISION_CONFLICT",
                    revision_fingerprint=revision_fingerprint,
                    now=now,
                    session_id_for_fk=envelope.session_id,
                )
                receipt = self._new_receipt(
                    envelope,
                    status=SyncAcknowledgementStatus.CONFLICT,
                    now=now,
                )
                self._session.add(receipt)
                self._session.flush()
                ack = self._acknowledgement_from_receipt(
                    receipt,
                    canonical_receipt_id=(existing_receipt.id if existing_receipt else None),
                    conflict_id=conflict.id,
                )
                return SyncIngestionResult(acknowledgement=ack)

            if decision.disposition is not RevisionDisposition.ACCEPT:
                raise RuntimeError(f"unhandled revision disposition: {decision.disposition}")

            # ACCEPT path. Everything below is canonical and remains in this one
            # transaction. No derived service is invoked here.
            self._upsert_machine(envelope)
            self._upsert_components(envelope)
            self._upsert_session(envelope)
            self._upsert_incidents(envelope)
            self._upsert_evidence(envelope)
            self._upsert_incident_relationships(envelope)
            self._upsert_maintenance(envelope)
            self._upsert_verification(envelope)
            self._enqueue_semantic_indexing(envelope)

            report = envelope.machine_session_report
            self._session.add(
                SessionReportRecord(
                    id=uuid4(),
                    report_id=report.report_id,
                    source_machine_id=envelope.source_machine_id,
                    session_id=envelope.session_id,
                    schema_version=envelope.schema_version,
                    report_revision=envelope.report_revision,
                    generated_at=report.generated_at,
                    ingested_at=now,
                    # This field stores the logical revision fingerprint rather
                    # than transport checksum so different package IDs with the
                    # same canonical revision remain idempotent.
                    checksum=revision_fingerprint,
                    payload=report.model_dump(mode="json"),
                )
            )
            receipt = self._new_receipt(
                envelope,
                status=SyncAcknowledgementStatus.ACCEPTED,
                now=now,
            )
            self._session.add(receipt)
            self._session.flush()
            ack = self._acknowledgement_from_receipt(receipt, canonical_receipt_id=receipt.id)

        # Exiting session.begin() above committed canonical truth before this
        # method exposes semantic work to the caller.
        return SyncIngestionResult(
            acknowledgement=ack,
            semantic_evidence_ids=semantic_ids,
        )

    def _upsert_machine(self, envelope: SyncEnvelope) -> None:
        source = envelope.machine_session_report.machine
        existing = self._session.get(MachineRecord, source.machine_id)
        if existing is None:
            if source.asset_code:
                collision = self._session.scalar(
                    select(MachineRecord).where(MachineRecord.asset_code == source.asset_code)
                )
                if collision is not None:
                    raise SyncIngestionError(
                        "MACHINE_ASSET_CODE_COLLISION",
                        "asset_code is already assigned to a different machine identity",
                        status_code=409,
                    )
            self._session.add(
                MachineRecord(
                    id=source.machine_id,
                    asset_code=source.asset_code,
                    display_name=source.display_name,
                    machine_type=source.machine_type,
                    manufacturer=source.manufacturer,
                    model=source.model,
                    site_name=source.site_name,
                    site_area=source.site_area,
                )
            )
            self._session.flush()
            return
        for name in (
            "asset_code",
            "display_name",
            "machine_type",
            "manufacturer",
            "model",
            "site_name",
            "site_area",
        ):
            value = getattr(source, name)
            if value is not None:
                setattr(existing, name, value)
        existing.updated_at = datetime.now(timezone.utc)

    def _upsert_components(self, envelope: SyncEnvelope) -> None:
        for source in envelope.machine_session_report.components:
            existing = self._session.get(ComponentRecord, source.component_id)
            if existing is None:
                self._session.add(
                    ComponentRecord(
                        id=source.component_id,
                        machine_id=source.machine_id,
                        display_name=source.display_name,
                        component_type=source.component_type,
                        manufacturer=source.manufacturer,
                        model=source.model,
                    )
                )
                continue
            if existing.machine_id != envelope.source_machine_id:
                raise SyncIngestionError(
                    "COMPONENT_MACHINE_MISMATCH",
                    "component identity is already owned by a different machine",
                    status_code=409,
                )
            for name in ("display_name", "component_type", "manufacturer", "model"):
                value = getattr(source, name)
                if value is not None:
                    setattr(existing, name, value)
        self._session.flush()

    def _upsert_session(self, envelope: SyncEnvelope) -> None:
        source = envelope.machine_session_report.session
        existing = self._session.get(OperatingSessionRecord, source.session_id)
        operating_hours = float(source.operating_hours) if source.operating_hours is not None else None
        if existing is None:
            self._session.add(
                OperatingSessionRecord(
                    id=source.session_id,
                    machine_id=source.machine_id,
                    started_at=source.started_at,
                    ended_at=source.ended_at,
                    state=source.state,
                    operating_hours=operating_hours,
                    latest_report_revision=envelope.report_revision,
                )
            )
            self._session.flush()
            return
        if existing.machine_id != source.machine_id:
            raise SyncIngestionError(
                "SESSION_MACHINE_MISMATCH",
                "session identity is already owned by a different machine",
                status_code=409,
            )
        existing.started_at = source.started_at
        existing.ended_at = source.ended_at
        existing.state = source.state
        existing.operating_hours = operating_hours
        existing.latest_report_revision = max(existing.latest_report_revision, envelope.report_revision)
        existing.updated_at = datetime.now(timezone.utc)
        self._session.flush()

    def _upsert_incidents(self, envelope: SyncEnvelope) -> None:
        for source in envelope.incident_updates:
            existing = self._session.get(IncidentRecord, source.incident_id)
            if existing is None:
                self._session.add(
                    IncidentRecord(
                        id=source.incident_id,
                        machine_id=source.machine_id,
                        component_id=source.component_id,
                        status=IncidentStatus(source.status),
                        owner_ref=source.owner_ref,
                        severity=source.severity,
                        due_state=source.due_state,
                        due_time=source.due_time,
                        first_seen_at=source.first_seen_at,
                        last_seen_at=source.last_seen_at,
                        source_report_revision=envelope.report_revision,
                    )
                )
                continue
            if existing.machine_id != source.machine_id:
                raise SyncIngestionError(
                    "INCIDENT_MACHINE_MISMATCH",
                    "incident identity is already owned by a different machine",
                    status_code=409,
                )
            existing.component_id = source.component_id
            existing.status = IncidentStatus(source.status)
            existing.owner_ref = source.owner_ref
            existing.severity = source.severity
            existing.due_state = source.due_state
            existing.due_time = source.due_time
            existing.first_seen_at = source.first_seen_at
            existing.last_seen_at = source.last_seen_at
            existing.source_report_revision = envelope.report_revision
            existing.updated_at = datetime.now(timezone.utc)
        self._session.flush()

    def _upsert_evidence(self, envelope: SyncEnvelope) -> None:
        raw_by_id = {
            item.evidence_id: item for item in envelope.optional_policy_selected_raw_evidence
        }
        for source in envelope.evidence_manifest.entries:
            existing = self._session.get(EvidenceEventRecord, source.evidence_id)
            if source.original_source_record_id is not None:
                source_collision = self._session.scalar(
                    select(EvidenceEventRecord).where(
                        EvidenceEventRecord.source_machine_id == source.source_machine_id,
                        EvidenceEventRecord.source_type == source.source_type,
                        EvidenceEventRecord.original_source_record_id == source.original_source_record_id,
                    )
                )
                if source_collision is not None and source_collision.id != source.evidence_id:
                    raise SyncIngestionError(
                        "EVIDENCE_SOURCE_IDENTITY_COLLISION",
                        "stable source evidence identity maps to a different evidence UUID",
                        status_code=409,
                    )
            if existing is not None:
                if (
                    existing.source_machine_id != source.source_machine_id
                    or existing.source_type != source.source_type
                    or existing.original_source_record_id != source.original_source_record_id
                ):
                    raise SyncIngestionError(
                        "EVIDENCE_UUID_COLLISION",
                        "evidence UUID already exists with incompatible source identity",
                        status_code=409,
                    )
                continue
            raw = raw_by_id.get(source.evidence_id)
            self._session.add(
                EvidenceEventRecord(
                    id=source.evidence_id,
                    machine_id=envelope.source_machine_id,
                    source_machine_id=source.source_machine_id,
                    session_id=source.session_id,
                    component_id=source.component_id,
                    source_type=source.source_type,
                    original_source_record_id=source.original_source_record_id,
                    original_timestamp=source.original_timestamp,
                    ingestion_timestamp=datetime.now(timezone.utc),
                    source_report_revision=envelope.report_revision,
                    canonical_event_type=source.canonical_event_type,
                    canonical_payload=source.canonical_payload,
                    raw_source_payload=(raw.raw_payload if raw is not None else {}),
                    provenance=source.provenance,
                    checksum=source.evidence_checksum,
                )
            )
        self._session.flush()

        for raw in envelope.optional_policy_selected_raw_evidence:
            if raw.attachment_id is None:
                continue
            if self._session.get(EvidenceAttachmentRecord, raw.attachment_id) is not None:
                continue
            self._session.add(
                EvidenceAttachmentRecord(
                    id=raw.attachment_id,
                    evidence_event_id=raw.evidence_id,
                    attachment_type=raw.attachment_type,
                    storage_reference=raw.storage_reference,
                    mime_type=raw.mime_type,
                    file_size=raw.file_size,
                    checksum=raw.checksum,
                    created_at=raw.created_at,
                )
            )
        self._session.flush()


    def _enqueue_semantic_indexing(self, envelope: SyncEnvelope) -> None:
        """Persist derived-work intent inside the canonical transaction.

        The row is not visible to another transaction until PostgreSQL commits,
        so no vector work can become eligible before canonical truth exists.
        """

        for selected in envelope.important_text_evidence:
            existing = self._session.scalar(
                select(SemanticIndexOutboxRecord).where(
                    SemanticIndexOutboxRecord.evidence_id == selected.evidence_id
                )
            )
            if existing is not None:
                continue
            self._session.add(
                SemanticIndexOutboxRecord(
                    id=uuid4(),
                    evidence_id=selected.evidence_id,
                    status=SemanticIndexOutboxStatus.PENDING.value,
                    source_report_revision=envelope.report_revision,
                )
            )
        self._session.flush()

    def _upsert_incident_relationships(self, envelope: SyncEnvelope) -> None:
        for incident in envelope.incident_updates:
            session_link = self._session.scalar(
                select(IncidentSessionLinkRecord).where(
                    IncidentSessionLinkRecord.incident_id == incident.incident_id,
                    IncidentSessionLinkRecord.session_id == envelope.session_id,
                )
            )
            if session_link is None:
                self._session.add(
                    IncidentSessionLinkRecord(
                        id=uuid4(),
                        incident_id=incident.incident_id,
                        session_id=envelope.session_id,
                        source_report_revision=envelope.report_revision,
                    )
                )

            for link in incident.evidence_links:
                existing = self._session.scalar(
                    select(IncidentEvidenceLinkRecord).where(
                        IncidentEvidenceLinkRecord.incident_id == incident.incident_id,
                        IncidentEvidenceLinkRecord.evidence_event_id == link.evidence_id,
                        IncidentEvidenceLinkRecord.is_active.is_(True),
                    )
                )
                if existing is None:
                    self._session.add(
                        IncidentEvidenceLinkRecord(
                            id=uuid4(),
                            incident_id=incident.incident_id,
                            evidence_event_id=link.evidence_id,
                            is_active=True,
                            relationship_type=IncidentEvidenceRelationshipType(link.relationship_type),
                            deterministic_rule_identifier=None,
                            link_reason=link.link_reason,
                            source_report_revision=envelope.report_revision,
                        )
                    )
        self._session.flush()

    def _upsert_maintenance(self, envelope: SyncEnvelope) -> None:
        for source in envelope.machine_session_report.maintenance_actions:
            existing = self._session.get(MaintenanceActionRecord, source.action_id)
            if existing is not None:
                if existing.machine_id != source.machine_id or existing.incident_id != source.incident_id:
                    raise SyncIngestionError(
                        "MAINTENANCE_ACTION_ID_COLLISION",
                        "maintenance action identity already exists with incompatible ownership",
                        status_code=409,
                    )
                continue
            self._session.add(
                MaintenanceActionRecord(
                    id=source.action_id,
                    machine_id=source.machine_id,
                    incident_id=source.incident_id,
                    session_id=source.session_id,
                    component_id=source.component_id,
                    action_type=source.action_type,
                    description=source.description,
                    original_timestamp=source.original_timestamp,
                    ingestion_timestamp=datetime.now(timezone.utc),
                    source_report_revision=envelope.report_revision,
                    provenance=source.provenance,
                )
            )
        self._session.flush()

    def _upsert_verification(self, envelope: SyncEnvelope) -> None:
        for source in envelope.machine_session_report.verification_runs:
            existing = self._session.get(VerificationRunRecord, source.verification_run_id)
            if existing is None:
                self._session.add(
                    VerificationRunRecord(
                        id=source.verification_run_id,
                        incident_id=source.incident_id,
                        session_id=source.session_id,
                        source_machine_id=source.source_machine_id,
                        verification_rule_id=None,
                        rule_identifier=source.rule_identifier,
                        result=(VerificationRunResult(source.result) if source.result else None),
                        started_at=source.started_at,
                        window_ends_at=source.window_ends_at,
                        completed_at=source.completed_at,
                        original_timestamp=source.original_timestamp,
                        ingestion_timestamp=datetime.now(timezone.utc),
                        source_report_revision=envelope.report_revision,
                        outcome_payload=source.outcome_payload,
                    )
                )
                self._session.flush()
            elif existing.incident_id != source.incident_id or existing.source_machine_id != source.source_machine_id:
                raise SyncIngestionError(
                    "VERIFICATION_RUN_ID_COLLISION",
                    "verification run identity already exists with incompatible ownership",
                    status_code=409,
                )

            for evidence_id in source.evidence_ids:
                link = self._session.scalar(
                    select(VerificationEvidenceRecord).where(
                        VerificationEvidenceRecord.verification_run_id == source.verification_run_id,
                        VerificationEvidenceRecord.evidence_event_id == evidence_id,
                    )
                )
                if link is None:
                    self._session.add(
                        VerificationEvidenceRecord(
                            id=uuid4(),
                            verification_run_id=source.verification_run_id,
                            evidence_event_id=evidence_id,
                        )
                    )
        self._session.flush()

    def _persist_conflict(
        self,
        *,
        envelope: SyncEnvelope,
        existing_receipt: SyncReceiptRecord | None,
        existing_report: SessionReportRecord | None,
        conflict_type: str,
        revision_fingerprint: str,
        now: datetime,
        session_id_for_fk: UUID,
    ) -> SyncConflictRecord:
        conflict = SyncConflictRecord(
            id=uuid4(),
            source_machine_id=envelope.source_machine_id,
            session_id=session_id_for_fk,
            incoming_package_id=envelope.package_id,
            existing_receipt_id=(existing_receipt.id if existing_receipt else None),
            conflict_type=conflict_type,
            incoming_report_revision=envelope.report_revision,
            existing_report_revision=(
                existing_report.report_revision
                if existing_report is not None
                else (existing_receipt.report_revision if existing_receipt else None)
            ),
            incoming_checksum=envelope.sync_metadata.checksum,
            existing_checksum=(
                existing_report.checksum
                if existing_report is not None
                else (existing_receipt.checksum if existing_receipt else None)
            ),
            incoming_metadata={
                "incoming_session_id": str(envelope.session_id),
                "incoming_schema_version": envelope.schema_version,
                "incoming_revision_fingerprint": revision_fingerprint,
            },
            existing_metadata={
                "existing_package_id": str(existing_receipt.package_id) if existing_receipt else None,
                "existing_session_id": str(existing_receipt.session_id) if existing_receipt else None,
                "existing_schema_version": existing_receipt.schema_version if existing_receipt else None,
                "existing_revision_fingerprint": existing_report.checksum if existing_report else None,
            },
            detected_at=now,
            resolution_status="UNRESOLVED",
        )
        self._session.add(conflict)
        self._session.flush()
        return conflict

    def _new_receipt(
        self,
        envelope: SyncEnvelope,
        *,
        status: SyncAcknowledgementStatus,
        now: datetime,
    ) -> SyncReceiptRecord:
        return SyncReceiptRecord(
            id=uuid4(),
            package_id=envelope.package_id,
            source_machine_id=envelope.source_machine_id,
            session_id=envelope.session_id,
            report_revision=envelope.report_revision,
            schema_version=envelope.schema_version,
            checksum=envelope.sync_metadata.checksum,
            acknowledgement_status=status.value,
            received_at=now,
            acknowledged_at=now,
        )

    def _find_accepted_receipt(
        self,
        machine_id: UUID,
        session_id: UUID,
        revision: int,
    ) -> SyncReceiptRecord | None:
        return self._session.scalar(
            select(SyncReceiptRecord)
            .where(
                SyncReceiptRecord.source_machine_id == machine_id,
                SyncReceiptRecord.session_id == session_id,
                SyncReceiptRecord.report_revision == revision,
                SyncReceiptRecord.acknowledgement_status == SyncAcknowledgementStatus.ACCEPTED.value,
            )
            .order_by(SyncReceiptRecord.received_at.asc(), SyncReceiptRecord.id.asc())
        )

    def _acknowledgement_from_receipt(
        self,
        receipt: SyncReceiptRecord,
        *,
        canonical_receipt_id: UUID | None = None,
        conflict_id: UUID | None = None,
    ) -> SyncAcknowledgement:
        received_at = receipt.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        if canonical_receipt_id is None and receipt.acknowledgement_status == SyncAcknowledgementStatus.ACCEPTED.value:
            canonical_receipt_id = receipt.id
        if conflict_id is None and receipt.acknowledgement_status == SyncAcknowledgementStatus.CONFLICT.value:
            conflict = self._session.scalar(
                select(SyncConflictRecord)
                .where(
                    SyncConflictRecord.source_machine_id == receipt.source_machine_id,
                    SyncConflictRecord.incoming_package_id == receipt.package_id,
                    SyncConflictRecord.incoming_report_revision == receipt.report_revision,
                    SyncConflictRecord.incoming_checksum == receipt.checksum,
                )
                .order_by(SyncConflictRecord.detected_at.asc(), SyncConflictRecord.id.asc())
            )
            conflict_id = conflict.id if conflict else None
        return SyncAcknowledgement(
            schema_version=receipt.schema_version,
            acknowledgement_id=receipt.id,
            package_id=receipt.package_id,
            source_machine_id=receipt.source_machine_id,
            session_id=receipt.session_id,
            report_revision=receipt.report_revision,
            status=SyncAcknowledgementStatus(receipt.acknowledgement_status),
            received_at=received_at,
            canonical_receipt_id=canonical_receipt_id,
            conflict_id=conflict_id,
        )
