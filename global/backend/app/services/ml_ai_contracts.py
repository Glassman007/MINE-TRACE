"""ML/AI service contracts and authority boundaries.

CANONICAL (outside ML/AI authority):
- evidence, provenance, timestamps
- incident state, verification, handover, audit history
- machine/component history and exact timeline
- deterministic incident linking and recurrence

DERIVED (allowed behind these interfaces):
- embeddings and semantic-index points
- vector similarity and semantic candidates
- model summaries and AI claims

Non-negotiable invariant: every ML-derived artifact may be deleted without
removing or changing canonical truth.
"""

from typing import Protocol
from uuid import UUID

from app.schemas.ai_provider import AIAnalysis
from app.schemas.ai_result import AIAnalysisFallbackReason, AIAnalysisResult
from app.schemas.ai_validation import AIValidationResult
from app.schemas.evidence_bundle import EvidenceBundleResponse
from app.schemas.semantic_history import SemanticHistoryResponse


class SemanticSearchService(Protocol):
    """Read-only semantic enrichment over canonical evidence identifiers."""

    def search_similar_history(self, evidence_id: UUID) -> SemanticHistoryResponse: ...


class EvidenceBundleBuilder(Protocol):
    """Build the deterministic, read-only boundary supplied to advisory AI."""

    def build(self, incident_id: UUID) -> EvidenceBundleResponse: ...


class AIOutputValidator(Protocol):
    """Validate one untrusted AI candidate against one sealed EvidenceBundle."""

    def validate(
        self,
        candidate: AIAnalysis | object,
        evidence_bundle: EvidenceBundleResponse,
    ) -> AIValidationResult: ...


class DeterministicFallback(Protocol):
    """Construct a non-model fallback from one sealed EvidenceBundle."""

    def build(
        self,
        evidence_bundle: EvidenceBundleResponse,
        reason: AIAnalysisFallbackReason,
    ) -> AIAnalysisResult: ...


__all__ = [
    "AIOutputValidator",
    "DeterministicFallback",
    "EvidenceBundleBuilder",
    "SemanticSearchService",
]
