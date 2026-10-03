"""Deterministic recurrence recording and occurrence reconstruction.

Recurrence is derived only from authoritative evidence/link state.  This module
contains no semantic retrieval, embeddings, ML, or LLM behavior and persists no
mutable occurrence counter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.core.time import normalize_to_utc
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.domain.lifecycle import validate_incident_transition
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
)
from app.repositories.unit_of_work import UnitOfWork
from app.services.verification import VerificationService


class RecurrenceError(RuntimeError):
    """Base class for deterministic recurrence failures."""


class UnknownIncidentForRecurrenceError(RecurrenceError):
    pass


class RecurrenceStage(StrEnum):
    """Internal test seam for proving transaction rollback after real flushes."""

    STATUS_UPDATED = "STATUS_UPDATED"
    RECURRENCE_AUDIT_APPENDED = "RECURRENCE_AUDIT_APPENDED"


@dataclass(frozen=True, slots=True)
class OccurrenceEntry:
    evidence_id: UUID
    link_id: UUID
    original_timestamp: datetime
    relationship_type: IncidentEvidenceRelationshipType


@dataclass(frozen=True, slots=True)
class OccurrenceReconstruction:
    incident_id: UUID
    occurrence_count: int
    occurrences: tuple[OccurrenceEntry, ...]

    @property
    def evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(item.evidence_id for item in self.occurrences)

    @property
    def recurrence_evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(
            item.evidence_id
            for item in self.occurrences
            if item.relationship_type == IncidentEvidenceRelationshipType.RECURRENCE
        )


class RecurrenceService:
    """Record genuine repeated events and rebuild occurrence state from evidence.

    Under the current MVP contract, active ``RELATED`` and ``RECURRENCE`` links
    are occurrence-bearing. ``VERIFICATION`` links are not.  The first incident
    evidence created by deterministic linking is ``RELATED``; subsequent genuine
    source records that match that incident are linked as ``RECURRENCE``.
    """

    def __init__(
        self,
        *,
        verification_service: VerificationService | None = None,
        fault_hook: Callable[[RecurrenceStage], None] | None = None,
    ) -> None:
        self._verification_service = verification_service
        self._fault_hook = fault_hook

    def record_recurrence(
        self,
        uow: UnitOfWork,
        *,
        incident: IncidentRecord,
        evidence: EvidenceEventRecord,
        link: IncidentEvidenceLinkRecord,
        rule_identifier: str,
        rule_name: str,
    ) -> None:
        """Record recurrence inside the caller-owned transaction.

        ``link`` must already be the active ``RECURRENCE`` association for the
        newly-created evidence.  The caller remains responsible for commit/rollback.
        """

        if link.relationship_type != IncidentEvidenceRelationshipType.RECURRENCE:
            raise RecurrenceError("recurrence recording requires a RECURRENCE link")

        status_before = incident.status
        status_after = status_before

        # If this genuine recurrence occurred inside a persisted verification
        # window, record it as VerificationEvidence and complete that run inside
        # this same ingestion transaction. The verification service does not own
        # the incident status mutation here; recurrence remains the lifecycle owner.
        if self._verification_service is not None:
            self._verification_service.record_recurrence_in_uow(
                uow,
                incident=incident,
                evidence=evidence,
            )

        # The domain lifecycle explicitly allows recurrence to reopen VERIFYING or
        # VERIFIED incidents as RECURRED. OPEN -> RECURRED is not an allowed
        # transition, so an OPEN incident records recurrence without an invalid
        # state mutation. An already RECURRED incident remains RECURRED.
        if status_before in {IncidentStatus.VERIFYING, IncidentStatus.VERIFIED}:
            validate_incident_transition(status_before, IncidentStatus.RECURRED)
            incident.status = IncidentStatus.RECURRED
            incident.updated_at = evidence.ingestion_timestamp
            status_after = IncidentStatus.RECURRED
            uow.incident_audit_events.add(
                IncidentAuditEventRecord(
                    id=uuid4(),
                    incident_id=incident.id,
                    action=IncidentAuditAction.STATUS_CHANGED,
                    occurred_at=evidence.ingestion_timestamp,
                    payload={
                        "from_status": status_before.value,
                        "to_status": IncidentStatus.RECURRED.value,
                        "reason": "genuine repeated evidence occurrence",
                        "evidence_event_id": str(evidence.id),
                        "incident_evidence_link_id": str(link.id),
                        "rule_identifier": rule_identifier,
                    },
                )
            )
            uow.flush()
            self._fault(RecurrenceStage.STATUS_UPDATED)

        uow.incident_audit_events.add(
            IncidentAuditEventRecord(
                id=uuid4(),
                incident_id=incident.id,
                action=IncidentAuditAction.RECURRENCE_RECORDED,
                occurred_at=evidence.ingestion_timestamp,
                payload={
                    "evidence_event_id": str(evidence.id),
                    "incident_evidence_link_id": str(link.id),
                    "relationship_type": IncidentEvidenceRelationshipType.RECURRENCE.value,
                    "rule_identifier": rule_identifier,
                    "rule_name": rule_name,
                    "status_before": status_before.value,
                    "status_after": status_after.value,
                },
            )
        )
        uow.flush()
        self._fault(RecurrenceStage.RECURRENCE_AUDIT_APPENDED)

    def reconstruct_occurrences(
        self,
        uow: UnitOfWork,
        incident_id: UUID,
    ) -> OccurrenceReconstruction:
        """Reconstruct active occurrence state deterministically from source evidence.

        No persisted counter participates. Ordering uses ``original_timestamp`` and
        then stable IDs, never ingestion or link time.
        """

        incident = uow.incidents.get(incident_id)
        if incident is None:
            raise UnknownIncidentForRecurrenceError(f"unknown incident: {incident_id}")

        entries: list[OccurrenceEntry] = []
        occurrence_types = {
            IncidentEvidenceRelationshipType.RELATED,
            IncidentEvidenceRelationshipType.RECURRENCE,
        }
        for link in uow.incident_evidence_links.list_active_for_incident(incident_id):
            if link.relationship_type not in occurrence_types:
                continue
            evidence = uow.evidence_events.get(link.evidence_event_id)
            if evidence is None:  # FK enforcement should make this unreachable.
                raise RecurrenceError(
                    f"active occurrence link references missing evidence: {link.evidence_event_id}"
                )
            entries.append(
                OccurrenceEntry(
                    evidence_id=evidence.id,
                    link_id=link.id,
                    original_timestamp=evidence.original_timestamp,
                    relationship_type=link.relationship_type,
                )
            )

        entries.sort(
            key=lambda item: (
                normalize_to_utc(item.original_timestamp),
                item.evidence_id,
                item.link_id,
            )
        )
        return OccurrenceReconstruction(
            incident_id=incident_id,
            occurrence_count=len(entries),
            occurrences=tuple(entries),
        )

    def reconstruct_occurrence_count(self, uow: UnitOfWork, incident_id: UUID) -> int:
        return self.reconstruct_occurrences(uow, incident_id).occurrence_count

    def _fault(self, stage: RecurrenceStage) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)
