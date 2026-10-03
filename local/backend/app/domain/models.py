from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from app.domain.enums import (
    ContextQuality,
    EvidenceBundleStatus,
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    VerificationRuleType,
    VerificationRunResult,
)

NonEmptyString = Annotated[str, Field(min_length=1)]
DomainTimestamp = AwareDatetime


class DomainModel(BaseModel):
    """Base configuration shared by canonical domain contracts."""

    model_config = ConfigDict(extra="forbid")


class ProvenanceRef(DomainModel):
    """Minimal source identity needed to retain evidence provenance."""

    source_system: NonEmptyString
    source_record_id: NonEmptyString | None = None


class Machine(DomainModel):
    id: UUID


class Component(DomainModel):
    id: UUID
    machine_id: UUID


class EvidenceEvent(DomainModel):
    id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    occurred_at: DomainTimestamp
    provenance: ProvenanceRef
    raw_payload: dict[str, JsonValue]


class EvidenceAttachment(DomainModel):
    id: UUID
    evidence_event_id: UUID
    attachment_type: NonEmptyString
    storage_reference: NonEmptyString
    mime_type: NonEmptyString
    file_size: Annotated[int, Field(ge=0)]
    checksum: NonEmptyString
    created_at: DomainTimestamp


class ContextDimension(DomainModel):
    value: JsonValue | None
    quality: ContextQuality
    freshness_basis: NonEmptyString


class ContextSnapshot(DomainModel):
    id: UUID
    evidence_event_id: UUID
    shift: ContextDimension
    location: ContextDimension
    machine_operating_state: ContextDimension
    workload: ContextDimension
    environment: ContextDimension


class Incident(DomainModel):
    id: UUID
    machine_id: UUID
    status: IncidentStatus


class IncidentEvidenceLink(DomainModel):
    id: UUID
    incident_id: UUID
    evidence_event_id: UUID
    relationship_type: IncidentEvidenceRelationshipType


class IncidentAuditEvent(DomainModel):
    id: UUID
    incident_id: UUID
    action: IncidentAuditAction
    occurred_at: DomainTimestamp


class VerificationRule(DomainModel):
    id: UUID
    identifier: NonEmptyString
    name: NonEmptyString
    rule_type: VerificationRuleType
    window_minutes: Annotated[int, Field(gt=0)]


class VerificationRun(DomainModel):
    id: UUID
    incident_id: UUID
    verification_rule_id: UUID
    result: VerificationRunResult | None = None
    started_at: DomainTimestamp
    window_ends_at: DomainTimestamp
    completed_at: DomainTimestamp | None = None


class VerificationEvidence(DomainModel):
    id: UUID
    verification_run_id: UUID
    evidence_event_id: UUID


class HandoverPacket(DomainModel):
    id: UUID
    created_at: datetime | None = None
    acknowledged_at: datetime | None = None


class HandoverItem(DomainModel):
    id: UUID
    handover_packet_id: UUID
    incident_id: UUID
    severity: str | None = None
    owner_ref: str | None = None
    status: IncidentStatus
    due_state: str | None = None
    due_time: datetime | None = None


class SyncChange(DomainModel):
    id: UUID


class SyncConflict(DomainModel):
    id: UUID


class EvidenceBundle(DomainModel):
    """Non-persisted deterministic evidence package contract."""

    incident_id: UUID
    status: EvidenceBundleStatus
    evidence_event_ids: tuple[UUID, ...] = ()
