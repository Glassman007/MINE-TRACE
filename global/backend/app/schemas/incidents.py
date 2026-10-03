"""Read-only incident API response contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.domain.enums import IncidentAuditAction, IncidentEvidenceRelationshipType, IncidentStatus


class IncidentAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    action: IncidentAuditAction
    occurred_at: datetime
    payload: dict[str, JsonValue]


class IncidentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    machine_id: UUID
    status: IncidentStatus
    owner_ref: str | None
    severity: str | None
    due_state: str | None
    due_time: datetime | None
    created_at: datetime
    updated_at: datetime
    audit_events: list[IncidentAuditOutput]


class IncidentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    machine_id: UUID
    status: IncidentStatus
    owner_ref: str | None
    severity: str | None
    due_state: str | None
    due_time: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IncidentSummaryResponse]
    total: int
    offset: int
    limit: int


class IncidentAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    audit_events: list[IncidentAuditOutput]


class IncidentEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: UUID
    evidence_id: UUID
    is_active: bool
    relationship_type: IncidentEvidenceRelationshipType
    deterministic_rule_identifier: str | None
    link_reason: str
    linked_at: datetime
    unlinked_at: datetime | None

    machine_id: UUID
    component_id: UUID | None
    source_type: str
    original_source_record_id: str
    original_timestamp: datetime
    canonical_event_type: str
    canonical_payload: dict[str, JsonValue]
    raw_source_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]


class IncidentEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    evidence: list[IncidentEvidenceItem]

class IncidentMaintenanceActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    machine_id: UUID
    incident_id: UUID
    session_id: UUID | None
    component_id: UUID | None
    action_type: str
    description: str | None
    original_timestamp: datetime
    ingestion_timestamp: datetime
    source_report_revision: int | None
    provenance: dict[str, JsonValue]


class IncidentMaintenanceActionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    actions: list[IncidentMaintenanceActionItem]
