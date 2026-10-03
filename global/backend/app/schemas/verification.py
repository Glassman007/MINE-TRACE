"""Read-only synchronized verification API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.domain.enums import VerificationRuleType, VerificationRunResult


class VerificationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    incident_id: UUID
    session_id: UUID | None = None
    source_machine_id: UUID
    verification_rule_id: UUID | None = None
    rule_identifier: str | None = None
    rule_name: str | None = None
    rule_type: VerificationRuleType | None = None
    window_minutes: int | None = None
    result: VerificationRunResult | None = None
    started_at: datetime
    window_ends_at: datetime | None = None
    completed_at: datetime | None = None
    original_timestamp: datetime | None = None
    source_report_revision: int | None = None
    outcome_payload: dict[str, JsonValue]
    evidence_event_ids: list[UUID]


class VerificationRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    runs: list[VerificationRunResponse]
