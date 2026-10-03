"""Replaceable advisory AI provider boundaries.

The current provider-neutral interface receives exactly one deterministic
EvidenceBundle and returns only derived, explicitly UNVALIDATED analysis. It is
not given repositories, UnitOfWork objects, database sessions, semantic-index
clients, Qdrant clients, or mutation capabilities.

The legacy LLMProvider protocol is retained temporarily for the already-accepted
guard/orchestration layer. The new AIProvider is intentionally separate so the
provider stage can be implemented without prematurely trusting model output.
"""

from typing import Protocol

from app.schemas.ai_provider import AIProviderResult
from app.schemas.evidence_bundle import EvidenceBundleResponse


class AIProviderUnavailableError(RuntimeError):
    """Legacy provider-unavailable exception used by accepted orchestration."""


class AIProvider(Protocol):
    """Vendor-neutral optional advisory analysis provider."""

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        """Return a typed provider result that is never considered validated."""
        ...


class LLMProvider(Protocol):
    """Backward-compatible serialized-provider boundary for accepted guards.

    New provider adapters should implement AIProvider instead. This protocol
    remains only so the existing validation/orchestration stage is not silently
    rewritten before its dedicated guard-layer pass.
    """

    def generate_analysis(self, evidence_bundle: EvidenceBundleResponse) -> str:
        """Return one serialized candidate analysis for deterministic validation."""
        ...


LLMProviderUnavailableError = AIProviderUnavailableError

__all__ = [
    "AIProvider",
    "AIProviderUnavailableError",
    "LLMProvider",
    "LLMProviderUnavailableError",
]
