"""Advisory AI orchestration over a sealed EvidenceBundle boundary."""

from __future__ import annotations

import logging

from app.integrations.llm import LLMProvider, LLMProviderUnavailableError
from app.schemas.ai_analysis import (
    AIAnalysisResponse,
    AIAnalysisStatus,
    AIFallbackReason,
)
from app.schemas.evidence_bundle import EvidenceBundleResponse
from app.services.ai_validation import (
    AIOutputValidationError,
    validate_citations,
    validate_claim_policy,
    validate_schema,
)

logger = logging.getLogger(__name__)


class AIOrchestrationService:
    """Validate advisory LLM analysis without repository/database capabilities."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    def analyze(self, bundle: EvidenceBundleResponse) -> AIAnalysisResponse:
        if self._provider is None:
            return self._fallback(AIFallbackReason.LLM_UNAVAILABLE)

        try:
            # Structural boundary: the provider receives the constructed bundle
            # and nothing else from the backend.
            raw_output = self._provider.generate_analysis(bundle)
        except TimeoutError:
            logger.warning("llm_analysis_timeout", extra={"incident_id": str(bundle.incident_id)})
            return self._fallback(AIFallbackReason.LLM_TIMEOUT)
        except LLMProviderUnavailableError:
            logger.warning("llm_analysis_unavailable", extra={"incident_id": str(bundle.incident_id)})
            return self._fallback(AIFallbackReason.LLM_UNAVAILABLE)
        except Exception as exc:
            logger.warning(
                "llm_analysis_failed",
                extra={
                    "incident_id": str(bundle.incident_id),
                    "error": type(exc).__name__,
                },
            )
            return self._fallback(AIFallbackReason.LLM_ERROR)

        try:
            output = validate_schema(raw_output)
            validate_citations(output, bundle)
            validate_claim_policy(output)
        except AIOutputValidationError as exc:
            logger.warning(
                "llm_analysis_validation_failed",
                extra={
                    "incident_id": str(bundle.incident_id),
                    "reason": exc.reason.value,
                },
            )
            return self._fallback(exc.reason)

        return AIAnalysisResponse(
            status=AIAnalysisStatus.VALIDATED,
            analysis=output,
            fallback_reason=None,
        )

    @staticmethod
    def _fallback(reason: AIFallbackReason) -> AIAnalysisResponse:
        # No timestamps, random IDs, provider text, or partial generated content:
        # identical failure class -> identical deterministic fallback shape.
        return AIAnalysisResponse(
            status=AIAnalysisStatus.FALLBACK,
            analysis=None,
            fallback_reason=reason,
        )
