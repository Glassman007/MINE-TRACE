"""Configuration-driven construction of optional advisory AI providers."""

from __future__ import annotations

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.core.settings import Settings
from app.integrations.llm.base import AIProvider
from app.integrations.llm.groq_provider import ClientFactory, GroqProvider
from app.schemas.ai_provider import AIProviderResult, AIProviderResultStatus
from app.schemas.evidence_bundle import EvidenceBundleResponse


class _StaticStateProvider(AIProvider):
    def __init__(
        self,
        status: AIProviderResultStatus,
        reason: str,
        observability: MLAIObservability | None = None,
    ) -> None:
        self._status = status
        self._reason = reason
        self._observability = observability or get_ml_ai_observability()

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        del evidence_bundle
        return AIProviderResult(status=self._status, analysis=None, reason=self._reason)

    def probe_availability(self) -> bool:
        status = (
            CapabilityStatus.DISABLED
            if self._status is AIProviderResultStatus.DISABLED
            else CapabilityStatus.UNAVAILABLE
        )
        self._observability.record_capability("ai_provider", status, self._reason)
        return False


def build_ai_provider(
    settings: Settings,
    *,
    groq_client_factory: ClientFactory | None = None,
    observability: MLAIObservability | None = None,
) -> AIProvider:
    """Build Groq only when explicitly enabled; otherwise return a degraded provider."""

    if not settings.ai_enabled:
        return _StaticStateProvider(AIProviderResultStatus.DISABLED, "ai_disabled", observability)

    provider = (settings.ai_provider or "").strip().lower()
    model = (settings.ai_model or "").strip()
    if not provider or not model:
        return _StaticStateProvider(
            AIProviderResultStatus.UNAVAILABLE,
            "missing_provider_or_model_configuration",
            observability,
        )
    if provider != "groq":
        return _StaticStateProvider(
            AIProviderResultStatus.UNAVAILABLE,
            "unsupported_ai_provider",
            observability,
        )
    if settings.groq_api_key is None:
        return _StaticStateProvider(
            AIProviderResultStatus.UNAVAILABLE,
            "missing_groq_api_key",
            observability,
        )

    kwargs = {
        "model": model,
        "api_key": settings.groq_api_key.get_secret_value(),
        "timeout_seconds": settings.ai_timeout_seconds,
        "observability": observability,
    }
    if groq_client_factory is not None:
        kwargs["client_factory"] = groq_client_factory
    try:
        return GroqProvider(**kwargs)
    except Exception:
        # Missing/corrupt SDK or client construction failure must degrade only
        # the explicit advisory AI action; canonical workflows remain usable.
        return _StaticStateProvider(
            AIProviderResultStatus.UNAVAILABLE,
            "provider_unavailable",
            observability,
        )


__all__ = ["build_ai_provider"]
