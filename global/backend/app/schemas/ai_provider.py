"""Unvalidated structured output produced by optional AI providers.

This module models provider output only. Parsing a model response into these
schemas proves structural shape, not factual correctness, citation validity, or
permission to mutate canonical MINE-TRACE state.
"""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIClaimType(StrEnum):
    EVENT_OCCURRED = "EVENT_OCCURRED"
    OBSERVATION_RECORDED = "OBSERVATION_RECORDED"
    MAINTENANCE_RECORDED = "MAINTENANCE_RECORDED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECURRENCE_RECORDED = "RECURRENCE_RECORDED"
    SIMILAR_HISTORY_FOUND = "SIMILAR_HISTORY_FOUND"
    CONTEXT_RECORDED = "CONTEXT_RECORDED"
    STATUS_REPORTED = "STATUS_REPORTED"


class AIAnalysisStatus(StrEnum):
    UNVALIDATED = "UNVALIDATED"


class AIClaim(BaseModel):
    """One structurally parsed model claim awaiting guard-layer validation."""

    model_config = ConfigDict(extra="forbid")

    claim_type: AIClaimType
    text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def citations_are_unique(self) -> "AIClaim":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must not contain duplicates")
        return self


class AIAnalysis(BaseModel):
    """Structured advisory model output that has *not* passed trust guards."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[AIAnalysisStatus.UNVALIDATED]
    summary: str = Field(min_length=1, max_length=8_000)
    claims: list[AIClaim] = Field(max_length=100)
    limitations: list[str] = Field(max_length=50)

    @model_validator(mode="after")
    def limitations_are_non_blank(self) -> "AIAnalysis":
        if any(not item.strip() for item in self.limitations):
            raise ValueError("limitations must not contain blank values")
        return self


class AIProviderResultStatus(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class AIProviderResult(BaseModel):
    """Typed provider execution result before guard-layer validation."""

    model_config = ConfigDict(extra="forbid")

    status: AIProviderResultStatus
    analysis: AIAnalysis | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def consistent_result(self) -> "AIProviderResult":
        if self.status is AIProviderResultStatus.UNVALIDATED:
            if self.analysis is None or self.reason is not None:
                raise ValueError("UNVALIDATED requires analysis and no reason")
            if self.analysis.status is not AIAnalysisStatus.UNVALIDATED:
                raise ValueError("provider analysis must remain UNVALIDATED")
        elif self.analysis is not None:
            raise ValueError("non-success provider results must not expose analysis")
        return self


__all__ = [
    "AIAnalysis",
    "AIAnalysisStatus",
    "AIClaim",
    "AIClaimType",
    "AIProviderResult",
    "AIProviderResultStatus",
]
