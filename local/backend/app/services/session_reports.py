from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.settings import Settings
from app.core.time import normalize_to_utc
from app.domain.enums import (
    EvidenceSourceType,
    IncidentStatus,
    OperatingSessionState,
    SessionReportAcknowledgementState,
)
from app.models import MachineSessionReportRecord, OperatingSessionRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.session_reports import (
    EvidenceAttachmentManifestReference,
    EvidenceManifest,
    EvidenceManifestEntry,
    MachineSessionReportResponse,
    SessionIncidentSummary,
    SessionMaintenanceAction,
    SessionOperatingSummary,
    SessionReportSyncMetadata,
    SessionUnresolvedWork,
    SessionVerificationResult,
)
from app.services.recurrence import RecurrenceService


class SessionReportError(RuntimeError):
    pass


class SessionReportNotFoundError(SessionReportError):
    pass


class SessionReportNotReadyError(SessionReportError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class MachineSessionReportService:
    """Build immutable session-close snapshots from authoritative SQLite state only."""

    REPORT_REVISION = 1

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._recurrence = RecurrenceService()

    def generate_in_uow(
        self,
        uow: UnitOfWork,
        session_record: OperatingSessionRecord,
    ) -> MachineSessionReportResponse:
        existing = uow.machine_session_reports.get_for_session(
            session_record.session_id,
            report_revision=self.REPORT_REVISION,
        )
        if existing is not None:
            return self._from_record(existing)

        if session_record.state != OperatingSessionState.CLOSED or session_record.ended_at is None:
            raise SessionReportNotReadyError(
                f"session must be closed before reporting: {session_record.session_id}"
            )

        evidence = list(uow.evidence_events.list_for_session(session_record.session_id))
        incident_ids: set[UUID] = set()
        manifest_entries: list[EvidenceManifestEntry] = []

        for item in evidence:
            links = list(uow.incident_evidence_links.list_active_for_evidence(item.id))
            active_incident_ids = sorted({link.incident_id for link in links}, key=str)
            incident_ids.update(active_incident_ids)
            authoritative_incident_id = (
                active_incident_ids[0] if len(active_incident_ids) == 1 else None
            )

            attachments = [
                EvidenceAttachmentManifestReference(
                    attachment_id=attachment.id,
                    storage_reference=attachment.storage_reference,
                    checksum=attachment.checksum,
                    mime_type=attachment.mime_type,
                    file_size=attachment.file_size,
                )
                for attachment in uow.evidence_attachments.list_for_evidence(item.id)
            ]
            attachments.sort(key=lambda attachment: str(attachment.attachment_id))

            checksum_source = {
                "evidence_id": str(item.id),
                "machine_id": str(item.machine_id),
                "session_id": str(item.session_id) if item.session_id is not None else None,
                "component_id": str(item.component_id) if item.component_id is not None else None,
                "source_type": item.source_type,
                "original_source_record_id": item.original_source_record_id,
                "original_timestamp": normalize_to_utc(item.original_timestamp).isoformat(),
                "canonical_event_type": item.canonical_event_type,
                "canonical_payload": item.canonical_payload,
                # Raw payload/provenance are hashed for integrity but are not embedded
                # in the synchronization manifest itself.
                "raw_source_payload": item.raw_source_payload,
                "provenance": item.provenance,
            }
            manifest_entries.append(
                EvidenceManifestEntry(
                    evidence_id=item.id,
                    machine_id=item.machine_id,
                    session_id=session_record.session_id,
                    component_id=item.component_id,
                    incident_id=authoritative_incident_id,
                    source_type=item.source_type,
                    original_timestamp=normalize_to_utc(item.original_timestamp),
                    provenance_reference=(
                        f"source-record:{quote(item.source_type, safe='')}:{quote(item.original_source_record_id, safe='')}"
                    ),
                    checksum=_sha256_json(checksum_source),
                    storage_references=attachments,
                )
            )

        manifest_entries.sort(
            key=lambda item: (normalize_to_utc(item.original_timestamp), str(item.evidence_id))
        )

        # An unresolved incident can legitimately span sessions without producing new
        # evidence in every session. Carry those authoritative machine-level items
        # into the close snapshot rather than silently dropping unresolved work.
        for incident in uow.incidents.list_for_machine(session_record.machine_id):
            if incident.status != IncidentStatus.VERIFIED:
                incident_ids.add(incident.id)

        incident_summaries: list[SessionIncidentSummary] = []
        for incident_id in sorted(incident_ids, key=str):
            incident = uow.incidents.get(incident_id)
            if incident is None:
                continue
            reconstruction = self._recurrence.reconstruct_occurrences(uow, incident_id)
            occurrence_evidence = [
                uow.evidence_events.get(entry.evidence_id)
                for entry in reconstruction.occurrences
            ]
            occurrence_evidence = [item for item in occurrence_evidence if item is not None]
            components = sorted(
                {item.component_id for item in occurrence_evidence if item.component_id is not None},
                key=str,
            )
            first_seen = (
                normalize_to_utc(reconstruction.occurrences[0].original_timestamp)
                if reconstruction.occurrences
                else None
            )
            last_seen = (
                normalize_to_utc(reconstruction.occurrences[-1].original_timestamp)
                if reconstruction.occurrences
                else None
            )
            incident_summaries.append(
                SessionIncidentSummary(
                    incident_id=incident.id,
                    component_id=components[0] if len(components) == 1 else None,
                    state=incident.status,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    occurrence_count=reconstruction.occurrence_count,
                    severity=incident.severity,
                )
            )

        incident_summaries.sort(key=lambda item: str(item.incident_id))
        summary_by_incident = {item.incident_id: item for item in incident_summaries}

        maintenance_actions = [
            SessionMaintenanceAction(
                evidence_id=item.id,
                component_id=item.component_id,
                action_type=item.canonical_event_type,
                original_timestamp=normalize_to_utc(item.original_timestamp),
                canonical_payload=item.canonical_payload,
            )
            for item in evidence
            if item.source_type == EvidenceSourceType.MAINTENANCE_RECORD.value
        ]
        maintenance_actions.sort(
            key=lambda item: (normalize_to_utc(item.original_timestamp), str(item.evidence_id))
        )

        verification_results: list[SessionVerificationResult] = []
        for incident_id in sorted(incident_ids, key=str):
            for run in uow.verification_runs.list_for_incident(incident_id):
                rule = uow.verification_rules.get(run.verification_rule_id)
                evidence_ids = [
                    link.evidence_event_id
                    for link in uow.verification_evidence.list_for_run(run.id)
                ]
                evidence_ids.sort(key=str)
                verification_results.append(
                    SessionVerificationResult(
                        verification_run_id=run.id,
                        incident_id=run.incident_id,
                        rule_identifier=rule.identifier if rule is not None else None,
                        result=run.result,
                        started_at=normalize_to_utc(run.started_at),
                        window_ends_at=(
                            normalize_to_utc(run.window_ends_at)
                            if run.window_ends_at is not None
                            else None
                        ),
                        completed_at=(
                            normalize_to_utc(run.completed_at)
                            if run.completed_at is not None
                            else None
                        ),
                        evidence_event_ids=evidence_ids,
                    )
                )
        verification_results.sort(
            key=lambda item: (
                str(item.incident_id),
                normalize_to_utc(item.started_at),
                str(item.verification_run_id),
            )
        )

        unresolved_work = [
            SessionUnresolvedWork(
                incident_id=item.incident_id,
                state=item.state,
                component_id=item.component_id,
            )
            for item in incident_summaries
            if item.state != IncidentStatus.VERIFIED
        ]

        report_id = uuid5(
            NAMESPACE_URL,
            f"mine-trace-session-report:{session_record.session_id}:{self.REPORT_REVISION}",
        )
        generated_at = normalize_to_utc(session_record.ended_at)
        base_payload = {
            "report_id": str(report_id),
            "machine_id": str(session_record.machine_id),
            "session_id": str(session_record.session_id),
            "schema_version": self._settings.transport_schema_version,
            "generated_at": generated_at.isoformat(),
            "operating_summary": SessionOperatingSummary(
                start=normalize_to_utc(session_record.started_at),
                end=generated_at,
                operating_hours=session_record.operating_hours,
                session_state=session_record.state,
            ).model_dump(mode="json", exclude_none=True),
            "incident_summaries": [
                item.model_dump(mode="json", exclude_none=True) for item in incident_summaries
            ],
            "maintenance_actions": [
                item.model_dump(mode="json", exclude_none=True) for item in maintenance_actions
            ],
            "verification_results": [
                item.model_dump(mode="json", exclude_none=True) for item in verification_results
            ],
            "unresolved_work": [
                item.model_dump(mode="json", exclude_none=True) for item in unresolved_work
            ],
            "evidence_manifest": EvidenceManifest(
                schema_version=self._settings.transport_schema_version,
                entries=manifest_entries,
            ).model_dump(
                mode="json", exclude_none=True
            ),
            "sync_metadata": SessionReportSyncMetadata(
                local_revision=session_record.revision,
                report_revision=self.REPORT_REVISION,
                acknowledgement_state=SessionReportAcknowledgementState.NOT_ACKNOWLEDGED,
            ).model_dump(mode="json"),
        }
        checksum = _sha256_json(base_payload)
        payload = {**base_payload, "checksum": checksum}
        response = MachineSessionReportResponse.model_validate(payload)

        uow.machine_session_reports.add(
            MachineSessionReportRecord(
                report_id=report_id,
                machine_id=session_record.machine_id,
                session_id=session_record.session_id,
                schema_version=self._settings.transport_schema_version,
                generated_at=generated_at,
                local_revision=session_record.revision,
                report_revision=self.REPORT_REVISION,
                acknowledgement_state=SessionReportAcknowledgementState.NOT_ACKNOWLEDGED,
                checksum=checksum,
                payload=response.model_dump(mode="json", exclude_none=True),
            )
        )
        uow.flush()
        return response

    def get_in_uow(
        self, uow: UnitOfWork, session_id: UUID
    ) -> MachineSessionReportResponse:
        record = uow.machine_session_reports.get_for_session(
            session_id, report_revision=self.REPORT_REVISION
        )
        if record is None:
            raise SessionReportNotFoundError(f"session report not found: {session_id}")
        return self._from_record(record)

    @staticmethod
    def _from_record(record: MachineSessionReportRecord) -> MachineSessionReportResponse:
        return MachineSessionReportResponse.model_validate(record.payload)
