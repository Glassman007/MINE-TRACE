"""Read-only incident retrieval over authoritative persistence."""

from collections.abc import Callable
from uuid import UUID

from app.core.time import restore_utc
from app.domain.enums import IncidentStatus
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.incidents import (
    IncidentAuditOutput,
    IncidentAuditResponse,
    IncidentCollectionResponse,
    IncidentDetailResponse,
    IncidentEvidenceItem,
    IncidentEvidenceResponse,
    IncidentSummaryResponse,
)


class IncidentQueryError(RuntimeError):
    pass


class UnknownIncidentError(IncidentQueryError):
    pass


class IncidentQueryService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def list_incidents(
        self,
        *,
        offset: int,
        limit: int,
        machine_id: UUID | None = None,
        status: IncidentStatus | None = None,
        severity: str | None = None,
        owner_ref: str | None = None,
        due_state: str | None = None,
    ) -> IncidentCollectionResponse:
        with self._uow_factory() as uow:
            rows = uow.incidents.list_collection(
                offset=offset,
                limit=limit,
                machine_id=machine_id,
                status=status,
                severity=severity,
                owner_ref=owner_ref,
                due_state=due_state,
            )
            total = uow.incidents.count_collection(
                machine_id=machine_id,
                status=status,
                severity=severity,
                owner_ref=owner_ref,
                due_state=due_state,
            )
            return IncidentCollectionResponse(
                items=[
                    IncidentSummaryResponse(
                        incident_id=row.id,
                        machine_id=row.machine_id,
                        status=row.status,
                        owner_ref=row.owner_ref,
                        severity=row.severity,
                        due_state=row.due_state,
                        due_time=restore_utc(row.due_time),
                        created_at=restore_utc(row.created_at),
                        updated_at=restore_utc(row.updated_at),
                    )
                    for row in rows
                ],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_incident(self, incident_id: UUID) -> IncidentDetailResponse:
        with self._uow_factory() as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise UnknownIncidentError(f"unknown incident: {incident_id}")

            audit_events = [
                IncidentAuditOutput(
                    id=audit.id,
                    action=audit.action,
                    occurred_at=restore_utc(audit.occurred_at),
                    payload=audit.payload,
                )
                for audit in uow.incident_audit_events.list_for_incident(incident_id)
            ]

            return IncidentDetailResponse(
                incident_id=incident.id,
                machine_id=incident.machine_id,
                status=incident.status,
                owner_ref=incident.owner_ref,
                severity=incident.severity,
                due_state=incident.due_state,
                due_time=restore_utc(incident.due_time),
                created_at=restore_utc(incident.created_at),
                updated_at=restore_utc(incident.updated_at),
                audit_events=audit_events,
            )

    def get_incident_audit(self, incident_id: UUID) -> IncidentAuditResponse:
        with self._uow_factory() as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise UnknownIncidentError(f"unknown incident: {incident_id}")
            return IncidentAuditResponse(
                incident_id=incident_id,
                audit_events=[
                    IncidentAuditOutput(
                        id=audit.id,
                        action=audit.action,
                        occurred_at=restore_utc(audit.occurred_at),
                        payload=audit.payload,
                    )
                    for audit in uow.incident_audit_events.list_for_incident(incident_id)
                ],
            )

    def get_incident_evidence(self, incident_id: UUID) -> IncidentEvidenceResponse:
        with self._uow_factory() as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise UnknownIncidentError(f"unknown incident: {incident_id}")

            items: list[IncidentEvidenceItem] = []
            for link in uow.incident_evidence_links.list_for_incident(incident_id):
                evidence = uow.evidence_events.get(link.evidence_event_id)
                if evidence is None:
                    # Authoritative FKs should make this impossible. Skipping would
                    # hide corruption, so fail loudly instead.
                    raise IncidentQueryError(
                        f"incident link {link.id} references missing evidence "
                        f"{link.evidence_event_id}"
                    )
                items.append(
                    IncidentEvidenceItem(
                        link_id=link.id,
                        evidence_id=evidence.id,
                        is_active=link.is_active,
                        relationship_type=link.relationship_type,
                        deterministic_rule_identifier=link.deterministic_rule_identifier,
                        link_reason=link.link_reason,
                        linked_at=restore_utc(link.linked_at),
                        unlinked_at=restore_utc(link.unlinked_at),
                        machine_id=evidence.machine_id,
                        component_id=evidence.component_id,
                        source_type=evidence.source_type,
                        original_source_record_id=evidence.original_source_record_id,
                        original_timestamp=restore_utc(evidence.original_timestamp),
                        canonical_event_type=evidence.canonical_event_type,
                        canonical_payload=evidence.canonical_payload,
                        raw_source_payload=evidence.raw_source_payload,
                        provenance=evidence.provenance,
                    )
                )

            return IncidentEvidenceResponse(incident_id=incident.id, evidence=items)
