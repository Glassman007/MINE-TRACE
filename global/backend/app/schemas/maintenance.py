"""Canonical maintenance-queue read contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import IncidentStatus, VerificationRunResult


class MaintenanceQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    incident_status: IncidentStatus
    due_state: str | None = None
    due_time: datetime | None = None
    site_name: str | None = None
    machine_model: str | None = None
    latest_maintenance_action_id: UUID | None = None
    latest_maintenance_action_type: str | None = None
    latest_maintenance_at: datetime | None = None
    latest_verification_run_id: UUID | None = None
    latest_verification_result: VerificationRunResult | None = None
    latest_verification_completed_at: datetime | None = None
    verification_required: bool
    updated_at: datetime


class MaintenanceQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[MaintenanceQueueItem]
    total: int
    offset: int
    limit: int
    ordering: str = "due_time_nulls_last,due_time_asc,updated_at_asc,incident_id_asc"
