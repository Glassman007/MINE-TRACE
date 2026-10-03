"""Provider-neutral AI analysis pipeline with deterministic fallback.

The pipeline does not own canonical state. It receives an already-built
EvidenceBundle, optionally asks the configured advisory provider for one
candidate, passes that candidate through the independent deterministic guard,
and otherwise returns a non-model fallback.
"""

from __future__ import annotations

from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.domain.enums import EvidenceBundleStatus
from app.integrations.llm.base import AIProvider
from app.schemas.ai_provider import AIProviderResultStatus
from app.schemas.ai_result import (
    AIAnalysisFallbackReason,
    AIAnalysisResult,
    AIAnalysisResultType,
    ValidatedAIAnalysis,
)
from app.schemas.ai_validation import AIValidationStage, AIValidationStatus
from app.schemas.evidence_bundle import EvidenceBundleResponse
from app.services.ai_fallback import DeterministicFallbackBuilder
from app.services.ai_validation import AIValidationGuard


class AIAnalysisPipeline:
    """Coordinate provider -> guard, falling back deterministically on failure."""

    def __init__(
        self,
        provider: AIProvider,
        *,
        validator: AIValidationGuard | None = None,
        fallback: DeterministicFallbackBuilder | None = None,
        observability: MLAIObservability | None = None,
    ) -> None:
        self._provider = provider
        self._observability = observability or get_ml_ai_observability()
        self._validator = validator or AIValidationGuard(self._observability)
        self._fallback = fallback or DeterministicFallbackBuilder()

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIAnalysisResult:
        # Insufficient canonical evidence is a deterministic precondition failure.
        # Do not invoke a model merely to restate that fact.
        if evidence_bundle.status is EvidenceBundleStatus.INSUFFICIENT_EVIDENCE:
            return self._fallback_result(
                evidence_bundle, AIAnalysisFallbackReason.INSUFFICIENT_EVIDENCE
            )

        try:
            provider_result = self._provider.analyze(evidence_bundle)
        except TimeoutError:
            self._observability.record_ai_provider_timeout()
            return self._fallback_result(evidence_bundle, AIAnalysisFallbackReason.AI_TIMEOUT)
        except Exception:
            # A provider adapter should normally convert remote failures into its
            # typed result contract. This defensive boundary prevents an
            # unexpected adapter exception from escaping into canonical flows.
            self._observability.record_ai_provider_error()
            return self._fallback_result(
                evidence_bundle, AIAnalysisFallbackReason.AI_PROVIDER_ERROR
            )

        if provider_result.status is not AIProviderResultStatus.UNVALIDATED:
            if provider_result.status is AIProviderResultStatus.TIMEOUT:
                self._observability.record_ai_provider_timeout()
            elif provider_result.status in {
                AIProviderResultStatus.PROVIDER_ERROR,
                AIProviderResultStatus.MALFORMED_RESPONSE,
            }:
                self._observability.record_ai_provider_error()
            if provider_result.status is AIProviderResultStatus.MALFORMED_RESPONSE:
                self._observability.record_ai_rejection(AIValidationStage.SCHEMA_VALIDATION.value)
            return self._fallback_result(
                evidence_bundle,
                self._provider_failure_reason(provider_result.status, provider_result.reason),
            )

        # AIProviderResult enforces that UNVALIDATED carries analysis.
        self._observability.record_ai_provider_success()
        assert provider_result.analysis is not None
        validation = self._validator.validate(provider_result.analysis, evidence_bundle)
        if validation.status is AIValidationStatus.REJECTED:
            assert validation.failure is not None
            return self._fallback_result(
                evidence_bundle, self._guard_failure_reason(validation.failure.stage)
            )

        assert validation.analysis is not None
        analysis = validation.analysis
        return AIAnalysisResult(
            result_type=AIAnalysisResultType.VALIDATED_AI,
            incident_id=evidence_bundle.incident_id,
            evidence_ids=self._canonical_evidence_ids(evidence_bundle),
            validated_ai=ValidatedAIAnalysis(
                summary=analysis.summary,
                claims=list(analysis.claims),
                limitations=list(analysis.limitations),
            ),
            fallback=None,
        )

    def _fallback_result(
        self,
        evidence_bundle: EvidenceBundleResponse,
        reason: AIAnalysisFallbackReason,
    ) -> AIAnalysisResult:
        self._observability.record_fallback(reason.value)
        return self._fallback.build(evidence_bundle, reason)

    @staticmethod
    def _canonical_evidence_ids(evidence_bundle: EvidenceBundleResponse) -> list:
        """Return stable canonical evidence IDs present in the sealed request bundle."""
        seen = set()
        ordered = []
        groups = (
            evidence_bundle.primary_incident_evidence,
            evidence_bundle.selected_exact_history,
            evidence_bundle.selected_semantic_history,
        )
        for group in groups:
            for item in group:
                if item.evidence_id not in seen:
                    seen.add(item.evidence_id)
                    ordered.append(item.evidence_id)
        for verification in evidence_bundle.verification_context:
            for evidence_id in verification.evidence_ids:
                if evidence_id not in seen:
                    seen.add(evidence_id)
                    ordered.append(evidence_id)
        return ordered

    @staticmethod
    def _provider_failure_reason(
        status: AIProviderResultStatus,
        provider_reason: str | None,
    ) -> AIAnalysisFallbackReason:
        if status is AIProviderResultStatus.DISABLED:
            return AIAnalysisFallbackReason.AI_DISABLED
        if status is AIProviderResultStatus.UNAVAILABLE:
            if provider_reason in {
                "missing_provider_or_model_configuration",
                "missing_groq_api_key",
            }:
                return AIAnalysisFallbackReason.AI_PROVIDER_NOT_CONFIGURED
            return AIAnalysisFallbackReason.AI_PROVIDER_UNAVAILABLE
        if status is AIProviderResultStatus.TIMEOUT:
            return AIAnalysisFallbackReason.AI_TIMEOUT
        if status is AIProviderResultStatus.MALFORMED_RESPONSE:
            return AIAnalysisFallbackReason.MALFORMED_OUTPUT
        if status is AIProviderResultStatus.PROVIDER_ERROR:
            return AIAnalysisFallbackReason.AI_PROVIDER_ERROR
        # Defensive default for future non-success provider states.
        return AIAnalysisFallbackReason.AI_PROVIDER_UNAVAILABLE

    @staticmethod
    def _guard_failure_reason(stage: AIValidationStage) -> AIAnalysisFallbackReason:
        if stage is AIValidationStage.SCHEMA_VALIDATION:
            return AIAnalysisFallbackReason.MALFORMED_OUTPUT
        if stage is AIValidationStage.CITATION_ID_VALIDATION:
            return AIAnalysisFallbackReason.UNKNOWN_CITATION
        return AIAnalysisFallbackReason.PROHIBITED_CLAIM


__all__ = ["AIAnalysisPipeline"]
