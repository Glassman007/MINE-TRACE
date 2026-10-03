"""Shift handover API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import IncidentStatus


class HandoverItemOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    incident_id: UUID
    severity: str | None
    owner_ref: str | None
    status: IncidentStatus
    due_state: str | None
    due_time: datetime | None


class HandoverPacketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    created_at: datetime
    acknowledged_at: datetime | None
    items: list[HandoverItemOutput]
