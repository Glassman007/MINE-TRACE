"""Exact relational fleet read contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import IncidentStatus


class FleetSessionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    machine_id: UUID
    started_at: datetime
    ended_at: datetime | None = None
    state: str
    operating_hours: float | None = None
    latest_report_revision: int
    ingested_at: datetime
    updated_at: datetime


class MachineSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: UUID
    items: list[FleetSessionItem]
    total: int
    offset: int
    limit: int


class FleetMachineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    display_name: str | None = None
    asset_code: str | None = None
    machine_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    site_name: str | None = None
    site_area: str | None = None
    latest_sync_received_at: datetime | None = None
    latest_acknowledged_at: datetime | None = None
    latest_acknowledgement_status: str | None = None
    latest_report_revision: int | None = None


class FleetMachineCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[FleetMachineItem]
    total: int
    offset: int
    limit: int


class FleetIncidentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    status: IncidentStatus
    owner_ref: str | None = None
    severity: str | None = None
    due_state: str | None = None
    due_time: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    source_report_revision: int | None = None
    machine_model: str | None = None
    site_name: str | None = None
    created_at: datetime
    updated_at: datetime


class FleetIncidentCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[FleetIncidentItem]
    total: int
    offset: int
    limit: int


class FleetOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fleet_machine_count: int
    recent_sessions: list[FleetSessionItem]
    unresolved_incident_count: int
    verification_states: dict[str, int]
    latest_sync_received_at: datetime | None = None
    latest_acknowledged_at: datetime | None = None
    acknowledgement_status_counts: dict[str, int]
    unresolved_sync_conflicts: int
