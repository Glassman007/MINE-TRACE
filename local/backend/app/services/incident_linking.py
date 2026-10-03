"""Deterministic, configuration-backed incident creation and evidence linking.

This module deliberately contains no semantic search, embeddings, ML, or LLM calls.
Every decision is derived from authoritative SQLite state plus typed configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.core.settings import Settings
from app.core.time import normalize_to_utc
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
)
from app.repositories.unit_of_work import UnitOfWork
from app.services.recurrence import RecurrenceService
from app.services.verification import VerificationService


class IncidentLinkingError(RuntimeError):
    """Base error for deterministic incident linking."""


class UnknownEvidenceForLinkingError(IncidentLinkingError):
    pass


@dataclass(frozen=True, slots=True)
class IncidentLinkingDecision:
    evidence_id: UUID
    incident_id: UUID
    link_id: UUID
    created_incident: bool
    rule_identifier: str
    rule_name: str
    relationship_type: IncidentEvidenceRelationshipType
    link_reason: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    incident: IncidentRecord
    anchor: EvidenceEventRecord
    delta_seconds: float


class IncidentLinkingService:
    """Apply the MVP's deterministic incident-linking rule.

    Compatibility is exact canonical-event-type equality by default. Additional
    symmetric compatible event pairs can be supplied via typed settings. Candidate
    component identity is derived from active linked evidence because the existing
    Incident persistence contract intentionally has no component column.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        recurrence_service: RecurrenceService | None = None,
    ) -> None:
        self._settings = settings
        self._recurrence_service = recurrence_service or RecurrenceService(
            verification_service=VerificationService(settings)
        )

    def link_new_evidence(
        self,
        uow: UnitOfWork,
        evidence: EvidenceEventRecord,
    ) -> IncidentLinkingDecision:
        """Link one newly-created evidence record inside the caller's transaction.

        The caller owns commit/rollback. Calling this again for evidence that already
        has an active link is idempotent and does not append another audit event.
        """

        existing_links = uow.incident_evidence_links.list_active_for_evidence(
            evidence.id
        )
        if existing_links:
            # Stable repository ordering makes this deterministic even if historical
            # data from another workflow contains more than one active association.
            existing_link = existing_links[0]
            incident = uow.incidents.get(existing_link.incident_id)
            if incident is None:  # Defensive: FK enforcement should prevent this.
                raise IncidentLinkingError(
                    f"active link references missing incident: {existing_link.incident_id}"
                )
            return IncidentLinkingDecision(
                evidence_id=evidence.id,
                incident_id=incident.id,
                link_id=existing_link.id,
                created_incident=False,
                rule_identifier=(
                    existing_link.deterministic_rule_identifier
                    or self._settings.incident_linking_rule_identifier
                ),
                rule_name=self._settings.incident_linking_rule_name,
                relationship_type=existing_link.relationship_type,
                link_reason=existing_link.link_reason,
            )

        candidates = self._eligible_candidates(uow, evidence)
        if candidates:
            chosen = min(
                candidates,
                key=lambda candidate: (
                    candidate.delta_seconds,
                    candidate.anchor.original_timestamp,
                    candidate.anchor.id,
                    candidate.incident.id,
                ),
            )
            incident = chosen.incident
            created_incident = False
            relationship_type = IncidentEvidenceRelationshipType.RECURRENCE
            link_reason = self._matched_reason(evidence, chosen)
        else:
            incident = IncidentRecord(
                id=uuid4(),
                machine_id=evidence.machine_id,
                status=IncidentStatus.OPEN,
            )
            uow.incidents.add(incident)
            uow.flush()
            created_incident = True
            relationship_type = IncidentEvidenceRelationshipType.RELATED
            link_reason = self._new_incident_reason(evidence)
            self._append_audit(
                uow,
                incident_id=incident.id,
                action=IncidentAuditAction.INCIDENT_CREATED,
                occurred_at=evidence.ingestion_timestamp,
                payload={
                    "evidence_event_id": str(evidence.id),
                    "rule_identifier": self._settings.incident_linking_rule_identifier,
                    "rule_name": self._settings.incident_linking_rule_name,
                    "reason": link_reason,
                },
            )

        link = IncidentEvidenceLinkRecord(
            id=uuid4(),
            incident_id=incident.id,
            evidence_event_id=evidence.id,
            is_active=True,
            relationship_type=relationship_type,
            deterministic_rule_identifier=self._settings.incident_linking_rule_identifier,
            link_reason=link_reason,
        )
        uow.incident_evidence_links.add(link)
        uow.flush()

        self._append_audit(
            uow,
            incident_id=incident.id,
            action=IncidentAuditAction.EVIDENCE_LINKED,
            occurred_at=evidence.ingestion_timestamp,
            payload={
                "evidence_event_id": str(evidence.id),
                "incident_evidence_link_id": str(link.id),
                "relationship_type": relationship_type.value,
                "rule_identifier": self._settings.incident_linking_rule_identifier,
                "rule_name": self._settings.incident_linking_rule_name,
                "link_reason": link_reason,
            },
        )
        uow.flush()

        if not created_incident:
            self._recurrence_service.record_recurrence(
                uow,
                incident=incident,
                evidence=evidence,
                link=link,
                rule_identifier=self._settings.incident_linking_rule_identifier,
                rule_name=self._settings.incident_linking_rule_name,
            )

        return IncidentLinkingDecision(
            evidence_id=evidence.id,
            incident_id=incident.id,
            link_id=link.id,
            created_incident=created_incident,
            rule_identifier=self._settings.incident_linking_rule_identifier,
            rule_name=self._settings.incident_linking_rule_name,
            relationship_type=relationship_type,
            link_reason=link_reason,
        )

    def link_evidence_by_id(
        self,
        uow: UnitOfWork,
        evidence_id: UUID,
    ) -> IncidentLinkingDecision:
        evidence = uow.evidence_events.get(evidence_id)
        if evidence is None:
            raise UnknownEvidenceForLinkingError(f"unknown evidence: {evidence_id}")
        return self.link_new_evidence(uow, evidence)

    def _eligible_candidates(
        self,
        uow: UnitOfWork,
        evidence: EvidenceEventRecord,
    ) -> list[_Candidate]:
        active_statuses = set(self._settings.incident_linking_active_statuses)
        window = timedelta(minutes=self._settings.incident_linking_window_minutes)
        candidates: list[_Candidate] = []

        for incident in uow.incidents.list_for_machine(evidence.machine_id):
            if incident.status not in active_statuses:
                continue

            matching_anchors: list[_Candidate] = []
            for link in uow.incident_evidence_links.list_active_for_incident(incident.id):
                anchor = uow.evidence_events.get(link.evidence_event_id)
                if anchor is None:  # Defensive: FK enforcement should prevent this.
                    continue
                if anchor.machine_id != evidence.machine_id:
                    continue
                # "Same component" is exact identity equality. Two machine-level
                # records with no component therefore compare equal; a component-level
                # record can never match a machine-level record.
                if anchor.component_id != evidence.component_id:
                    continue
                if not self._event_types_are_compatible(
                    anchor.canonical_event_type,
                    evidence.canonical_event_type,
                ):
                    continue

                delta = abs(
                    normalize_to_utc(evidence.original_timestamp)
                    - normalize_to_utc(anchor.original_timestamp)
                )
                if delta > window:
                    continue
                matching_anchors.append(
                    _Candidate(
                        incident=incident,
                        anchor=anchor,
                        delta_seconds=delta.total_seconds(),
                    )
                )

            if matching_anchors:
                candidates.append(
                    min(
                        matching_anchors,
                        key=lambda candidate: (
                            candidate.delta_seconds,
                            candidate.anchor.original_timestamp,
                            candidate.anchor.id,
                        ),
                    )
                )

        return candidates

    def _event_types_are_compatible(self, left: str, right: str) -> bool:
        if self._settings.incident_linking_allow_identical_event_type and left == right:
            return True

        pairs = self._settings.incident_linking_compatible_event_pairs
        return right in pairs.get(left, ()) or left in pairs.get(right, ())

    def _matched_reason(
        self,
        evidence: EvidenceEventRecord,
        candidate: _Candidate,
    ) -> str:
        return (
            f"Matched rule {self._settings.incident_linking_rule_identifier}: "
            f"same machine {evidence.machine_id}; same component {evidence.component_id}; "
            f"compatible event types {candidate.anchor.canonical_event_type!r} and "
            f"{evidence.canonical_event_type!r}; source-time delta "
            f"{candidate.delta_seconds:.3f}s within configured "
            f"{self._settings.incident_linking_window_minutes} minute window; "
            f"anchor evidence {candidate.anchor.id}."
        )

    def _new_incident_reason(self, evidence: EvidenceEventRecord) -> str:
        return (
            f"Created new incident under rule "
            f"{self._settings.incident_linking_rule_identifier}: no active incident "
            f"had evidence satisfying same-machine, same-component, compatible-event, "
            f"and configured {self._settings.incident_linking_window_minutes} minute "
            f"source-time window criteria for evidence {evidence.id}."
        )

    @staticmethod
    def _append_audit(
        uow: UnitOfWork,
        *,
        incident_id: UUID,
        action: IncidentAuditAction,
        occurred_at,
        payload: dict[str, object],
    ) -> None:
        uow.incident_audit_events.add(
            IncidentAuditEventRecord(
                id=uuid4(),
                incident_id=incident_id,
                action=action,
                occurred_at=occurred_at,
                payload=payload,
            )
        )
