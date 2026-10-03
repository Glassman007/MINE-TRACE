"""Typed results for deterministic AI guard validation.

The validator is independent of the model provider.  It accepts one already
produced candidate analysis plus the exact EvidenceBundle supplied to that model
request and returns a deterministic trust decision.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.ai_provider import AIAnalysis


class AIValidationStage(StrEnum):
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    CITATION_ID_VALIDATION = "CITATION_ID_VALIDATION"
    CLAIM_POLICY_VALIDATION = "CLAIM_POLICY_VALIDATION"


class AIValidationStatus(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class AIValidationFailureCode(StrEnum):
    INVALID_SCHEMA = "INVALID_SCHEMA"
    MALFORMED_EVIDENCE_ID = "MALFORMED_EVIDENCE_ID"
    CITATION_NOT_IN_BUNDLE = "CITATION_NOT_IN_BUNDLE"

    ROOT_CAUSE_AUTHORITY_EXCEEDED = "ROOT_CAUSE_AUTHORITY_EXCEEDED"
    MAINTENANCE_CERTIFICATION_PROHIBITED = "MAINTENANCE_CERTIFICATION_PROHIBITED"
    REPAIR_GUARANTEE_PROHIBITED = "REPAIR_GUARANTEE_PROHIBITED"
    FAILURE_GUARANTEE_PROHIBITED = "FAILURE_GUARANTEE_PROHIBITED"
    NO_FAILURE_GUARANTEE_PROHIBITED = "NO_FAILURE_GUARANTEE_PROHIBITED"
    AUTHORITATIVE_MAINTENANCE_INSTRUCTION = "AUTHORITATIVE_MAINTENANCE_INSTRUCTION"
    INCIDENT_STATE_TRANSITION_PROHIBITED = "INCIDENT_STATE_TRANSITION_PROHIBITED"
    VERIFICATION_OUTCOME_NOT_ESTABLISHED = "VERIFICATION_OUTCOME_NOT_ESTABLISHED"
    RECURRENCE_NOT_ESTABLISHED = "RECURRENCE_NOT_ESTABLISHED"
    OWNERSHIP_CHANGE_PROHIBITED = "OWNERSHIP_CHANGE_PROHIBITED"
    SEVERITY_CHANGE_PROHIBITED = "SEVERITY_CHANGE_PROHIBITED"


class AIValidationFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: AIValidationStage
    code: AIValidationFailureCode
    detail: str = Field(min_length=1, max_length=1_000)
    claim_index: int | None = Field(default=None, ge=0)


class AIValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AIValidationStatus
    analysis: AIAnalysis | None = None
    failure: AIValidationFailure | None = None

    @model_validator(mode="after")
    def status_is_consistent(self) -> "AIValidationResult":
        if self.status is AIValidationStatus.VALIDATED:
            if self.analysis is None or self.failure is not None:
                raise ValueError("VALIDATED requires analysis and no failure")
        else:
            if self.analysis is not None or self.failure is None:
                raise ValueError("REJECTED requires failure and no analysis")
        return self


__all__ = [
    "AIValidationFailure",
    "AIValidationFailureCode",
    "AIValidationResult",
    "AIValidationStage",
    "AIValidationStatus",
]
