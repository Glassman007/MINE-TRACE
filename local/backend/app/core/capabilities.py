"""Runtime readiness state for optional MINE-TRACE capabilities.

These states are advisory integration readiness only. They never alter
canonical persistence, incident linking, recurrence, verification, handover,
or audit behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Protocol

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CapabilityState:
    status: CapabilityStatus
    reason: str | None = None


class CapabilityStateTarget(Protocol):
    state: object


def semantic_configuration_state(settings: Settings) -> CapabilityState:
    if not settings.semantic_search_enabled:
        return CapabilityState(CapabilityStatus.DISABLED, "semantic_search_disabled")

    missing: list[str] = []
    if not settings.qdrant_url and not settings.qdrant_location:
        missing.append("qdrant_url_or_location")
    if not settings.qdrant_collection:
        missing.append("qdrant_collection")
    if not settings.embedding_provider:
        missing.append("embedding_provider")
    if not settings.embedding_model:
        missing.append("embedding_model")

    if missing:
        return CapabilityState(
            CapabilityStatus.UNAVAILABLE,
            "missing_configuration:" + ",".join(missing),
        )
    return CapabilityState(CapabilityStatus.AVAILABLE, "configured")


def embedding_configuration_state(settings: Settings) -> CapabilityState:
    if not settings.semantic_search_enabled:
        return CapabilityState(CapabilityStatus.DISABLED, "semantic_search_disabled")
    missing: list[str] = []
    if not settings.embedding_provider:
        missing.append("embedding_provider")
    if not settings.embedding_model:
        missing.append("embedding_model")
    if missing:
        return CapabilityState(
            CapabilityStatus.UNAVAILABLE,
            "missing_configuration:" + ",".join(missing),
        )
    # Configuration is not proof of provider health. Runtime capability reporting
    # must verify the provider before it can become AVAILABLE.
    return CapabilityState(CapabilityStatus.UNAVAILABLE, "configured_unverified")


def ai_configuration_state(settings: Settings) -> CapabilityState:
    if not settings.ai_enabled:
        return CapabilityState(CapabilityStatus.DISABLED, "ai_disabled")

    missing: list[str] = []
    if not settings.ai_provider:
        missing.append("ai_provider")
    if not settings.ai_model:
        missing.append("ai_model")

    # API keys are provider-specific. The selected Groq hosted adapter requires one.
    if (settings.ai_provider or "").strip().lower() == "groq" and settings.groq_api_key is None:
        missing.append("groq_api_key")

    if missing:
        return CapabilityState(
            CapabilityStatus.UNAVAILABLE,
            "missing_configuration:" + ",".join(missing),
        )
    return CapabilityState(CapabilityStatus.UNAVAILABLE, "configured_unverified")


def probe_qdrant(settings: Settings) -> None:
    """Best-effort connectivity probe; raises when Qdrant cannot be reached.

    This does not create collections, index evidence, or perform semantic search.
    """

    if not settings.qdrant_url and not settings.qdrant_location:
        raise RuntimeError("Qdrant URL or local location is not configured")

    from app.integrations.qdrant import QdrantAvailability, QdrantService

    service = QdrantService.from_settings(settings)
    result = service.connectivity()
    if result.availability is QdrantAvailability.UNAVAILABLE:
        raise RuntimeError(result.reason or "Qdrant unavailable")


def initialize_capability_states(app: CapabilityStateTarget, settings: Settings) -> None:
    """Populate non-authoritative runtime capability state without failing startup."""

    semantic_state = semantic_configuration_state(settings)
    observability = getattr(app.state, "ml_ai_observability", None)
    if semantic_state.status is CapabilityStatus.AVAILABLE:
        try:
            probe_qdrant(settings)
        except Exception as exc:  # optional dependency must never own startup
            if observability is not None:
                observability.record_qdrant_connectivity_failure()
            logger.warning(
                "qdrant_unavailable_at_startup",
                extra={"error": type(exc).__name__},
            )
            semantic_state = CapabilityState(
                CapabilityStatus.UNAVAILABLE,
                "qdrant_unavailable",
            )

    embedding_state = embedding_configuration_state(settings)
    ai_state = ai_configuration_state(settings)
    app.state.semantic_retrieval_capability = semantic_state
    app.state.embedding_provider_capability = embedding_state
    app.state.ai_capability = ai_state
    if observability is not None:
        observability.record_capability(
            "qdrant_semantic", semantic_state.status, semantic_state.reason
        )
        observability.record_capability(
            "embedding_provider", embedding_state.status, embedding_state.reason
        )
        observability.record_capability("ai_provider", ai_state.status, ai_state.reason)
