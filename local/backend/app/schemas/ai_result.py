"""Final advisory AI-analysis result contracts.

These contracts separate a guard-validated model analysis from a deterministic
fallback.  A fallback is never model-generated and must not be presented as a
successful live AI response.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    VerificationRuleType,
    VerificationRunResult,
)
from app.schemas.ai_provider import AIClaim


class AIAnalysisResultType(StrEnum):
    VALIDATED_AI = "VALIDATED_AI"
    FALLBACK = "FALLBACK"


class AIAnalysisFallbackReason(StrEnum):
    AI_DISABLED = "AI_DISABLED"
    AI_PROVIDER_NOT_CONFIGURED = "AI_PROVIDER_NOT_CONFIGURED"
    AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    AI_PROVIDER_ERROR = "AI_PROVIDER_ERROR"
    AI_TIMEOUT = "AI_TIMEOUT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    UNKNOWN_CITATION = "UNKNOWN_CITATION"
    PROHIBITED_CLAIM = "PROHIBITED_CLAIM"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SemanticEnrichmentState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"


class ValidatedAIAnalysis(BaseModel):
    """Model output that has passed the independent deterministic guard."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["VALIDATED"] = "VALIDATED"
    summary: str
    claims: list[AIClaim]
    limitations: list[str]


class FallbackEvidenceFact(BaseModel):
    """Canonical fact copied from a sealed EvidenceBundle.

    Similarity metadata is intentionally omitted here. The deterministic
    fallback communicates canonical evidence facts, not model confidence or
    semantic-equivalence probabilities.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    evidence_type: str
    canonical_event_type: str
    original_timestamp: datetime
    canonical_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    source_classification: EvidenceBundleSourceClassification


class FallbackVerificationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_run_id: UUID
    rule_identifier: str | None
    rule_name: str | None
    rule_type: VerificationRuleType | None
    result: VerificationRunResult | None
    started_at: datetime
    window_ends_at: datetime | None
    completed_at: datetime | None
    evidence_ids: list[UUID] = Field(default_factory=list)


class SemanticEnrichmentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SemanticEnrichmentState
    configured: bool
    attempted: bool
    selected_match_count: int = Field(ge=0)
    failure_reasons: list[str] = Field(default_factory=list)


class DeterministicAIFallback(BaseModel):
    """Typed non-model result assembled only from the EvidenceBundle."""

    model_config = ConfigDict(extra="forbid")

    reason: AIAnalysisFallbackReason
    reason_detail: str
    incident_id: UUID
    evidence_bundle_status: EvidenceBundleStatus
    primary_evidence: list[FallbackEvidenceFact]
    exact_history: list[FallbackEvidenceFact]
    semantic_history: SemanticEnrichmentSummary
    verification: list[FallbackVerificationFact]


class AIAnalysisResult(BaseModel):
    """Stable result envelope for validated AI or deterministic fallback."""

    model_config = ConfigDict(extra="forbid")

    result_type: AIAnalysisResultType
    incident_id: UUID
    evidence_ids: list[UUID] = Field(default_factory=list)
    validated_ai: ValidatedAIAnalysis | None = None
    fallback: DeterministicAIFallback | None = None

    @model_validator(mode="after")
    def result_shape_matches_type(self) -> "AIAnalysisResult":
        if self.result_type is AIAnalysisResultType.VALIDATED_AI:
            if self.validated_ai is None or self.fallback is not None:
                raise ValueError("VALIDATED_AI requires validated_ai and no fallback")
        else:
            if self.fallback is None or self.validated_ai is not None:
                raise ValueError("FALLBACK requires fallback and no validated_ai")
        return self


__all__ = [
    "AIAnalysisFallbackReason",
    "AIAnalysisResult",
    "AIAnalysisResultType",
    "DeterministicAIFallback",
    "FallbackEvidenceFact",
    "FallbackVerificationFact",
    "SemanticEnrichmentState",
    "SemanticEnrichmentSummary",
    "ValidatedAIAnalysis",
]
