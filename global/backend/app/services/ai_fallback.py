"""Deterministic AI fallback construction.

This module never calls an LLM, database, Qdrant, or any mutation service. It
only projects already-typed deterministic EvidenceBundle data into an explicit
fallback result.
"""

from __future__ import annotations

from app.schemas.ai_result import (
    AIAnalysisFallbackReason,
    AIAnalysisResult,
    AIAnalysisResultType,
    DeterministicAIFallback,
    FallbackEvidenceFact,
    FallbackVerificationFact,
    SemanticEnrichmentState,
    SemanticEnrichmentSummary,
)
from app.schemas.evidence_bundle import BundleEvidenceItem, EvidenceBundleResponse


_REASON_DETAIL: dict[AIAnalysisFallbackReason, str] = {
    AIAnalysisFallbackReason.AI_DISABLED: "AI analysis is disabled by configuration.",
    AIAnalysisFallbackReason.AI_PROVIDER_NOT_CONFIGURED: (
        "AI analysis is unavailable because the configured provider is incomplete."
    ),
    AIAnalysisFallbackReason.AI_PROVIDER_UNAVAILABLE: (
        "AI analysis is unavailable because the provider cannot currently be used."
    ),
    AIAnalysisFallbackReason.AI_PROVIDER_ERROR: (
        "AI analysis failed because the provider returned an execution error."
    ),
    AIAnalysisFallbackReason.AI_TIMEOUT: "AI analysis timed out.",
    AIAnalysisFallbackReason.MALFORMED_OUTPUT: (
        "AI output was rejected because it did not satisfy the required structured schema."
    ),
    AIAnalysisFallbackReason.UNKNOWN_CITATION: (
        "AI output was rejected because at least one cited evidence ID was not supplied in this request."
    ),
    AIAnalysisFallbackReason.PROHIBITED_CLAIM: (
        "AI output was rejected because at least one claim exceeded advisory AI authority."
    ),
    AIAnalysisFallbackReason.INSUFFICIENT_EVIDENCE: (
        "AI analysis was not attempted because the deterministic EvidenceBundle is insufficient."
    ),
}


class DeterministicFallbackBuilder:
    """Build deterministic fallback output from one sealed EvidenceBundle."""

    def build(
        self,
        evidence_bundle: EvidenceBundleResponse,
        reason: AIAnalysisFallbackReason,
    ) -> AIAnalysisResult:
        semantic = evidence_bundle.completeness.semantic_retrieval
        if not semantic.configured:
            semantic_state = SemanticEnrichmentState.DISABLED
        elif semantic.failed:
            semantic_state = SemanticEnrichmentState.UNAVAILABLE
        else:
            semantic_state = SemanticEnrichmentState.AVAILABLE

        return AIAnalysisResult(
            result_type=AIAnalysisResultType.FALLBACK,
            validated_ai=None,
            fallback=DeterministicAIFallback(
                reason=reason,
                reason_detail=_REASON_DETAIL[reason],
                incident_id=evidence_bundle.incident_id,
                evidence_bundle_status=evidence_bundle.status,
                primary_evidence=[
                    self._evidence_fact(item)
                    for item in evidence_bundle.primary_incident_evidence
                ],
                exact_history=[
                    self._evidence_fact(item)
                    for item in evidence_bundle.selected_exact_history
                ],
                semantic_history=SemanticEnrichmentSummary(
                    state=semantic_state,
                    configured=semantic.configured,
                    attempted=semantic.attempted,
                    selected_match_count=(
                        len(evidence_bundle.selected_semantic_history)
                        if semantic_state is SemanticEnrichmentState.AVAILABLE
                        else 0
                    ),
                    failure_reasons=[failure.value for failure in semantic.failures],
                ),
                verification=[
                    FallbackVerificationFact(
                        verification_run_id=item.verification_run_id,
                        rule_identifier=item.rule_identifier,
                        rule_name=item.rule_name,
                        rule_type=item.rule_type,
                        result=item.result,
                        started_at=item.started_at,
                        window_ends_at=item.window_ends_at,
                        completed_at=item.completed_at,
                        evidence_ids=list(item.evidence_ids),
                    )
                    for item in evidence_bundle.verification_context
                ],
            ),
        )

    @staticmethod
    def _evidence_fact(item: BundleEvidenceItem) -> FallbackEvidenceFact:
        return FallbackEvidenceFact(
            evidence_id=item.evidence_id,
            machine_id=item.machine_id,
            component_id=item.component_id,
            evidence_type=item.source_type,
            canonical_event_type=item.canonical_event_type,
            original_timestamp=item.original_timestamp,
            canonical_payload=item.canonical_payload,
            provenance=item.provenance,
            source_classification=item.source_classification,
        )


__all__ = ["DeterministicFallbackBuilder"]
