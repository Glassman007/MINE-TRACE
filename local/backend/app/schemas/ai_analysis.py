"""Strict structured contracts for advisory AI analysis."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIAnalysisStatus(StrEnum):
    VALIDATED = "VALIDATED"
    FALLBACK = "FALLBACK"


class AIFallbackReason(StrEnum):
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_ERROR = "LLM_ERROR"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    CITATION_VALIDATION_FAILED = "CITATION_VALIDATION_FAILED"
    CLAIM_POLICY_VALIDATION_FAILED = "CLAIM_POLICY_VALIDATION_FAILED"


class CitedAIClaim(BaseModel):
    """One evidence-grounded claim.

    Every normal AI claim must cite at least one EvidenceBundle evidence ID.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_citations(self) -> "CitedAIClaim":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must not contain duplicates")
        return self


class AIAnalysisOutput(BaseModel):
    """The only structured content accepted from an LLM."""

    model_config = ConfigDict(extra="forbid")

    summary: CitedAIClaim
    relevant_observations: list[CitedAIClaim] = Field(default_factory=list, max_length=50)
    possible_historical_similarities: list[CitedAIClaim] = Field(
        default_factory=list, max_length=50
    )
    unresolved_contradictions: list[CitedAIClaim] = Field(default_factory=list, max_length=50)
    evidence_references: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_reference_index(self) -> "AIAnalysisOutput":
        if len(self.evidence_references) != len(set(self.evidence_references)):
            raise ValueError("evidence_references must not contain duplicates")
        return self

    def claims(self) -> list[CitedAIClaim]:
        return [
            self.summary,
            *self.relevant_observations,
            *self.possible_historical_similarities,
            *self.unresolved_contradictions,
        ]


class AIAnalysisResponse(BaseModel):
    """Stable API/service envelope.

    A fallback intentionally contains no generated analysis. This prevents a
    validation failure from being disguised as advisory content.
    """

    model_config = ConfigDict(extra="forbid")

    status: AIAnalysisStatus
    analysis: AIAnalysisOutput | None
    fallback_reason: AIFallbackReason | None

    @model_validator(mode="after")
    def consistent_status(self) -> "AIAnalysisResponse":
        if self.status is AIAnalysisStatus.VALIDATED:
            if self.analysis is None or self.fallback_reason is not None:
                raise ValueError("VALIDATED requires analysis and no fallback_reason")
        else:
            if self.analysis is not None or self.fallback_reason is None:
                raise ValueError("FALLBACK requires fallback_reason and no analysis")
        return self
