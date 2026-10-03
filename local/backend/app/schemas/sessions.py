from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.enums import OperatingSessionState


class OperatingSessionOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime


class OperatingSessionCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ended_at: AwareDatetime
    operating_hours: float | None = Field(default=None, ge=0)


class OperatingSessionRolloverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ended_at: AwareDatetime
    new_started_at: AwareDatetime
    operating_hours: float | None = Field(default=None, ge=0)


class OperatingSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    machine_id: UUID
    started_at: datetime
    ended_at: datetime | None
    state: OperatingSessionState
    operating_hours: float | None
    revision: int
    created_at: datetime
    updated_at: datetime


class OperatingSessionRolloverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed_session: OperatingSessionResponse
    new_session: OperatingSessionResponse
