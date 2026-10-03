"""Auditable deterministic return-to-service API contract."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ReturnToServiceState


class ReturnToServiceBlockingReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    incident_id: UUID | None = None
    verification_id: UUID | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)


class ReturnToServiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ReturnToServiceState
    blocking_reasons: list[ReturnToServiceBlockingReason] = Field(default_factory=list)
    incident_ids: list[UUID] = Field(default_factory=list)
    verification_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    policy_identifier: str
    policy_revision: int
