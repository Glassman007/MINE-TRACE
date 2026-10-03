from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import VerificationRuleType, VerificationRunResult


class VerificationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    incident_id: UUID
    verification_rule_id: UUID
    rule_identifier: str
    rule_name: str
    rule_type: VerificationRuleType
    window_minutes: int
    result: VerificationRunResult | None
    started_at: datetime
    window_ends_at: datetime
    completed_at: datetime | None
    evidence_event_ids: list[UUID]


class VerificationRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    runs: list[VerificationRunResponse]


class DueVerificationEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluated: list[VerificationRunResponse]
