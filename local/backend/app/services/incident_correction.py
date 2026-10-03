"""Atomic, explicit correction of incident/evidence associations.

Corrections are deterministic because callers name the source association and either
name the destination incident (`move_evidence`) or explicitly request a new incident
(`split_incident`). No AI, semantic retrieval, or heuristic incident selection occurs
in this module.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from app.core.settings import Settings, get_settings
from app.core.time import normalize_to_utc
from app.domain.enums import IncidentAuditAction, IncidentStatus
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
)
from app.repositories.unit_of_work import UnitOfWork


class IncidentCorrectionError(RuntimeError):
    """Base error for explicit incident-association correction."""


class UnknownCorrectionIncidentError(IncidentCorrectionError):
    pass


class UnknownCorrectionEvidenceError(IncidentCorrectionError):
    pass


class ActiveAssociationNotFoundError(IncidentCorrectionError):
    pass


class AmbiguousActiveAssociationError(IncidentCorrectionError):
    pass


class InvalidCorrectionTargetError(IncidentCorrectionError):
    pass


class CorrectionStage(StrEnum):
    """Internal deterministic stages exposed only as a fault-injection seam."""

    OLD_LINK_DEACTIVATED = "OLD_LINK_DEACTIVATED"
    EVIDENCE_UNLINKED_AUDIT_APPENDED = "EVIDENCE_UNLINKED_AUDIT_APPENDED"
    NEW_INCIDENT_CREATED = "NEW_INCIDENT_CREATED"
    NEW_LINK_CREATED = "NEW_LINK_CREATED"
    EVIDENCE_LINKED_AUDIT_APPENDED = "EVIDENCE_LINKED_AUDIT_APPENDED"
    INCIDENT_SPLIT_AUDIT_APPENDED = "INCIDENT_SPLIT_AUDIT_APPENDED"


@dataclass(frozen=True, slots=True)
class EvidenceMoveResult:
    source_incident_id: UUID
    target_incident_id: UUID
    evidence_id: UUID
    old_link_id: UUID
    new_link_id: UUID


@dataclass(frozen=True, slots=True)
class IncidentSplitResult:
    source_incident_id: UUID
    new_incident_id: UUID
    evidence_ids: tuple[UUID, ...]
    old_link_ids: tuple[UUID, ...]
    new_link_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class _CorrectionItem:
    evidence: EvidenceEventRecord
    old_link: IncidentEvidenceLinkRecord


FaultHook = Callable[[CorrectionStage], None]
Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


class IncidentCorrectionService:
    """Move evidence associations without ever deleting source evidence.

    The service owns one UnitOfWork per public operation. Every persistence stage is
    flushed inside that transaction so integration tests can inject an exception after
    a real intermediate database mutation and prove that rollback restores the prior
    authoritative state.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        settings: Settings | None = None,
        clock: Clock | None = None,
        uuid_factory: UuidFactory = uuid4,
        fault_hook: FaultHook | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._uuid_factory = uuid_factory
        self._fault_hook = fault_hook

    def move_evidence(
        self,
        *,
        source_incident_id: UUID,
        evidence_id: UUID,
        target_incident_id: UUID,
        reason: str,
    ) -> EvidenceMoveResult:
        """Move one active evidence association to an explicit existing incident."""

        self._require_reason(reason)
        if source_incident_id == target_incident_id:
            raise InvalidCorrectionTargetError(
                "source and target incident must be different"
            )

        with self._uow_factory() as uow:
            source = self._require_incident(uow, source_incident_id)
            target = self._require_incident(uow, target_incident_id)
            item = self._resolve_correction_item(uow, source, evidence_id)

            if target.machine_id != item.evidence.machine_id:
                raise InvalidCorrectionTargetError(
                    "target incident belongs to a different machine"
                )
            if uow.incident_evidence_links.list_active_for_incident(target.id):
                # Existing evidence on the target is allowed. This read intentionally
                # performs no compatibility inference: the caller selected the target.
                pass
            if any(
                link.incident_id == target.id
                for link in uow.incident_evidence_links.list_active_for_evidence(
                    evidence_id
                )
            ):
                raise InvalidCorrectionTargetError(
                    "evidence is already actively associated with target incident"
                )

            occurred_at = normalize_to_utc(self._clock())
            old_link_id, new_link_id = self._move_item(
                uow,
                source=source,
                target=target,
                item=item,
                reason=reason,
                occurred_at=occurred_at,
            )
            uow.commit()
            return EvidenceMoveResult(
                source_incident_id=source.id,
                target_incident_id=target.id,
                evidence_id=evidence_id,
                old_link_id=old_link_id,
                new_link_id=new_link_id,
            )

    def split_incident(
        self,
        *,
        source_incident_id: UUID,
        evidence_ids: Sequence[UUID],
        reason: str,
    ) -> IncidentSplitResult:
        """Create one new OPEN incident and move explicit evidence into it atomically."""

        self._require_reason(reason)
        unique_evidence_ids = tuple(dict.fromkeys(evidence_ids))
        if not unique_evidence_ids:
            raise InvalidCorrectionTargetError(
                "split requires at least one evidence id"
            )
        if len(unique_evidence_ids) != len(evidence_ids):
            raise InvalidCorrectionTargetError(
                "split evidence ids must be unique"
            )

        with self._uow_factory() as uow:
            source = self._require_incident(uow, source_incident_id)
            items = [
                self._resolve_correction_item(uow, source, evidence_id)
                for evidence_id in unique_evidence_ids
            ]

            # Validate the entire request before the first mutation. All evidence in
            # an incident split must remain on the same machine as the source incident.
            if any(item.evidence.machine_id != source.machine_id for item in items):
                raise InvalidCorrectionTargetError(
                    "split evidence belongs to a different machine"
                )

            occurred_at = normalize_to_utc(self._clock())

            # Steps 1-2: deactivate every old association and append unlink audits.
            old_link_ids: list[UUID] = []
            for item in items:
                old_link_ids.append(
                    self._deactivate_old_link(
                        uow,
                        source=source,
                        item=item,
                        reason=reason,
                        occurred_at=occurred_at,
                    )
                )

            # Step 3: create the new incident. New incidents start at OPEN because
            # OPEN is the canonical initial lifecycle state established by the MVP.
            new_incident = IncidentRecord(
                id=self._uuid_factory(),
                machine_id=source.machine_id,
                status=IncidentStatus.OPEN,
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            uow.incidents.add(new_incident)
            # Repositories intentionally do not define ORM relationships, so flush
            # the FK parent before appending audit rows that reference it.
            uow.flush()
            self._append_audit(
                uow,
                incident_id=new_incident.id,
                action=IncidentAuditAction.INCIDENT_CREATED,
                occurred_at=occurred_at,
                payload={
                    "source_incident_id": str(source.id),
                    "evidence_ids": [str(item.evidence.id) for item in items],
                    "rule_identifier": self._settings.incident_correction_rule_identifier,
                    "rule_name": self._settings.incident_correction_rule_name,
                    "reason": reason,
                },
            )
            uow.flush()
            self._after(CorrectionStage.NEW_INCIDENT_CREATED)

            # Steps 4-5: create new links and linked audit events.
            new_link_ids: list[UUID] = []
            for item in items:
                new_link_ids.append(
                    self._create_new_link(
                        uow,
                        target=new_incident,
                        item=item,
                        source_incident_id=source.id,
                        reason=reason,
                        occurred_at=occurred_at,
                    )
                )

            # Step 6: record the split on the source incident.
            self._append_audit(
                uow,
                incident_id=source.id,
                action=IncidentAuditAction.INCIDENT_SPLIT,
                occurred_at=occurred_at,
                payload={
                    "new_incident_id": str(new_incident.id),
                    "evidence_ids": [str(item.evidence.id) for item in items],
                    "old_link_ids": [str(link_id) for link_id in old_link_ids],
                    "new_link_ids": [str(link_id) for link_id in new_link_ids],
                    "rule_identifier": self._settings.incident_correction_rule_identifier,
                    "rule_name": self._settings.incident_correction_rule_name,
                    "reason": reason,
                },
            )
            uow.flush()
            self._after(CorrectionStage.INCIDENT_SPLIT_AUDIT_APPENDED)

            # Step 7: one commit for the entire correction transaction.
            uow.commit()
            return IncidentSplitResult(
                source_incident_id=source.id,
                new_incident_id=new_incident.id,
                evidence_ids=tuple(item.evidence.id for item in items),
                old_link_ids=tuple(old_link_ids),
                new_link_ids=tuple(new_link_ids),
            )

    def _move_item(
        self,
        uow: UnitOfWork,
        *,
        source: IncidentRecord,
        target: IncidentRecord,
        item: _CorrectionItem,
        reason: str,
        occurred_at: datetime,
    ) -> tuple[UUID, UUID]:
        old_link_id = self._deactivate_old_link(
            uow,
            source=source,
            item=item,
            reason=reason,
            occurred_at=occurred_at,
        )
        new_link_id = self._create_new_link(
            uow,
            target=target,
            item=item,
            source_incident_id=source.id,
            reason=reason,
            occurred_at=occurred_at,
        )
        return old_link_id, new_link_id

    def _deactivate_old_link(
        self,
        uow: UnitOfWork,
        *,
        source: IncidentRecord,
        item: _CorrectionItem,
        reason: str,
        occurred_at: datetime,
    ) -> UUID:
        deactivated = uow.incident_evidence_links.deactivate(
            item.old_link.id,
            unlinked_at=occurred_at,
        )
        if deactivated is None:  # Defensive: item was resolved in this transaction.
            raise ActiveAssociationNotFoundError(
                f"active incident/evidence link disappeared: {item.old_link.id}"
            )
        uow.flush()
        self._after(CorrectionStage.OLD_LINK_DEACTIVATED)

        self._append_audit(
            uow,
            incident_id=source.id,
            action=IncidentAuditAction.EVIDENCE_UNLINKED,
            occurred_at=occurred_at,
            payload={
                "evidence_event_id": str(item.evidence.id),
                "incident_evidence_link_id": str(item.old_link.id),
                "rule_identifier": self._settings.incident_correction_rule_identifier,
                "rule_name": self._settings.incident_correction_rule_name,
                "reason": reason,
            },
        )
        uow.flush()
        self._after(CorrectionStage.EVIDENCE_UNLINKED_AUDIT_APPENDED)
        return item.old_link.id

    def _create_new_link(
        self,
        uow: UnitOfWork,
        *,
        target: IncidentRecord,
        item: _CorrectionItem,
        source_incident_id: UUID,
        reason: str,
        occurred_at: datetime,
    ) -> UUID:
        link = IncidentEvidenceLinkRecord(
            id=self._uuid_factory(),
            incident_id=target.id,
            evidence_event_id=item.evidence.id,
            is_active=True,
            relationship_type=item.old_link.relationship_type,
            deterministic_rule_identifier=self._settings.incident_correction_rule_identifier,
            link_reason=(
                f"Explicit correction from incident {source_incident_id}: {reason}"
            ),
            linked_at=occurred_at,
        )
        uow.incident_evidence_links.add(link)
        uow.flush()
        self._after(CorrectionStage.NEW_LINK_CREATED)

        self._append_audit(
            uow,
            incident_id=target.id,
            action=IncidentAuditAction.EVIDENCE_LINKED,
            occurred_at=occurred_at,
            payload={
                "evidence_event_id": str(item.evidence.id),
                "incident_evidence_link_id": str(link.id),
                "source_incident_id": str(source_incident_id),
                "relationship_type": item.old_link.relationship_type.value,
                "rule_identifier": self._settings.incident_correction_rule_identifier,
                "rule_name": self._settings.incident_correction_rule_name,
                "reason": reason,
            },
        )
        uow.flush()
        self._after(CorrectionStage.EVIDENCE_LINKED_AUDIT_APPENDED)
        return link.id

    def _resolve_correction_item(
        self,
        uow: UnitOfWork,
        source: IncidentRecord,
        evidence_id: UUID,
    ) -> _CorrectionItem:
        evidence = uow.evidence_events.get(evidence_id)
        if evidence is None:
            raise UnknownCorrectionEvidenceError(f"unknown evidence: {evidence_id}")
        if evidence.machine_id != source.machine_id:
            raise ActiveAssociationNotFoundError(
                "evidence does not belong to the source incident machine"
            )

        active_links = list(
            uow.incident_evidence_links.list_active_for_evidence(evidence_id)
        )
        source_links = [
            link for link in active_links if link.incident_id == source.id
        ]
        if not source_links:
            raise ActiveAssociationNotFoundError(
                f"evidence {evidence_id} has no active association with incident {source.id}"
            )
        if len(active_links) != 1 or len(source_links) != 1:
            raise AmbiguousActiveAssociationError(
                f"evidence {evidence_id} has ambiguous active incident associations"
            )

        return _CorrectionItem(evidence=evidence, old_link=source_links[0])

    @staticmethod
    def _require_incident(uow: UnitOfWork, incident_id: UUID) -> IncidentRecord:
        incident = uow.incidents.get(incident_id)
        if incident is None:
            raise UnknownCorrectionIncidentError(f"unknown incident: {incident_id}")
        return incident

    @staticmethod
    def _require_reason(reason: str) -> None:
        if not reason.strip():
            raise InvalidCorrectionTargetError("correction reason must not be blank")

    def _after(self, stage: CorrectionStage) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def _append_audit(
        self,
        uow: UnitOfWork,
        *,
        incident_id: UUID,
        action: IncidentAuditAction,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> None:
        uow.incident_audit_events.add(
            IncidentAuditEventRecord(
                id=self._uuid_factory(),
                incident_id=incident_id,
                action=action,
                occurred_at=occurred_at,
                payload=payload,
            )
        )
