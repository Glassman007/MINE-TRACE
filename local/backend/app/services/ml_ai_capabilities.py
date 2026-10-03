"""Honest, non-authoritative runtime capability checks for ML/AI integrations."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.integrations.embeddings.factory import build_embedding_provider
from app.integrations.llm.factory import build_ai_provider
from app.integrations.qdrant import QdrantAvailability, QdrantService
from app.schemas.ml_ai_observability import (
    MLAICapabilityReport,
    MLAIOperationalSignals,
    OperationalCapability,
)


_CAPABILITY_PROBE_TEXT = "MINE-TRACE operational capability probe"


def build_ml_ai_capability_report(
    *,
    app_state: Any,
    settings: Settings,
    observability: MLAIObservability,
) -> MLAICapabilityReport:
    """Probe optional integrations without changing canonical domain truth.

    AVAILABLE is never inferred solely from environment/configuration. Qdrant is
    actively contacted. Embedding/AI providers must either support an explicit
    probe or have a successful runtime observation recorded by the operational
    layer.
    """

    qdrant = _qdrant_capability(app_state, settings, observability)
    embedding = _embedding_capability(app_state, settings, observability)
    ai = _ai_capability(app_state, settings, observability)
    signals = observability.snapshot()

    return MLAICapabilityReport(
        qdrant_semantic=qdrant,
        embedding_provider=embedding,
        ai_provider=ai,
        signals=MLAIOperationalSignals(**asdict(signals)),
    )


def _qdrant_capability(
    app_state: Any,
    settings: Settings,
    observability: MLAIObservability,
) -> OperationalCapability:
    if not settings.semantic_search_enabled:
        return _reported(
            observability,
            "qdrant_semantic",
            CapabilityStatus.DISABLED,
            "semantic_search_disabled",
        )
    if (not settings.qdrant_url and not settings.qdrant_location) or not settings.qdrant_collection:
        return _reported(
            observability,
            "qdrant_semantic",
            CapabilityStatus.UNAVAILABLE,
            "missing_qdrant_configuration",
        )

    service = getattr(app_state, "qdrant_service", None)
    if service is None:
        try:
            service = QdrantService.from_settings(
                settings,
                observability=observability,
            )
        except Exception:
            return _reported(
                observability,
                "qdrant_semantic",
                CapabilityStatus.UNAVAILABLE,
                "qdrant_service_unavailable",
            )

    connectivity = service.connectivity()
    if connectivity.availability is QdrantAvailability.UNAVAILABLE:
        return _reported(
            observability,
            "qdrant_semantic",
            CapabilityStatus.UNAVAILABLE,
            "qdrant_unavailable",
        )

    collections = service.discover_collections()
    if collections.availability is QdrantAvailability.UNAVAILABLE:
        return _reported(
            observability,
            "qdrant_semantic",
            CapabilityStatus.UNAVAILABLE,
            "qdrant_unavailable",
        )
    if settings.qdrant_collection not in collections.collections:
        return _reported(
            observability,
            "qdrant_semantic",
            CapabilityStatus.UNAVAILABLE,
            "semantic_collection_missing",
        )
    if settings.embedding_vector_dimension is not None:
        collection = service.validate_collection(vector_size=settings.embedding_vector_dimension)
        if collection.availability is QdrantAvailability.UNAVAILABLE:
            return _reported(
                observability, "qdrant_semantic", CapabilityStatus.UNAVAILABLE, "qdrant_unavailable"
            )
        if not collection.compatible:
            return _reported(
                observability,
                "qdrant_semantic",
                CapabilityStatus.UNAVAILABLE,
                collection.reason or "semantic_collection_incompatible",
            )
    return _reported(
        observability,
        "qdrant_semantic",
        CapabilityStatus.AVAILABLE,
        "connectivity_verified",
    )


def _embedding_capability(
    app_state: Any,
    settings: Settings,
    observability: MLAIObservability,
) -> OperationalCapability:
    if not settings.semantic_search_enabled:
        return _reported(
            observability,
            "embedding_provider",
            CapabilityStatus.DISABLED,
            "semantic_search_disabled",
            provider=settings.embedding_provider,
            model=settings.embedding_model,
        )
    if not settings.embedding_provider or not settings.embedding_model:
        return _reported(
            observability,
            "embedding_provider",
            CapabilityStatus.UNAVAILABLE,
            "missing_embedding_configuration",
            provider=settings.embedding_provider,
            model=settings.embedding_model,
        )

    provider = getattr(app_state, "embedding_provider", None)
    if provider is None:
        try:
            provider = build_embedding_provider(
                settings,
                observability=observability,
            )
        except Exception:
            return _reported(
                observability,
                "embedding_provider",
                CapabilityStatus.UNAVAILABLE,
                "embedding_provider_unavailable",
                provider=settings.embedding_provider,
                model=settings.embedding_model,
            )

    probe = getattr(provider, "probe_availability", None)
    try:
        if callable(probe):
            ok = bool(probe())
        else:
            # Providers without a dedicated lightweight probe are verified by a
            # synthetic query embedding. No canonical/user payload is sent.
            provider.embed_query(_CAPABILITY_PROBE_TEXT)
            ok = True
    except Exception:
        ok = False

    return _reported(
        observability,
        "embedding_provider",
        CapabilityStatus.AVAILABLE if ok else CapabilityStatus.UNAVAILABLE,
        "provider_probe_succeeded" if ok else "provider_probe_failed",
        provider=settings.embedding_provider,
        model=settings.embedding_model,
    )


def _ai_capability(
    app_state: Any,
    settings: Settings,
    observability: MLAIObservability,
) -> OperationalCapability:
    if not settings.ai_enabled:
        return _reported(
            observability,
            "ai_provider",
            CapabilityStatus.DISABLED,
            "ai_disabled",
            provider=settings.ai_provider,
            model=settings.ai_model,
        )
    if not settings.ai_provider or not settings.ai_model:
        return _reported(
            observability,
            "ai_provider",
            CapabilityStatus.UNAVAILABLE,
            "missing_ai_configuration",
            provider=settings.ai_provider,
            model=settings.ai_model,
        )

    provider = getattr(app_state, "ai_provider", None)
    if provider is None:
        provider = build_ai_provider(settings, observability=observability)

    probe = getattr(provider, "probe_availability", None)
    if callable(probe):
        try:
            ok = bool(probe())
        except Exception:
            ok = False
    else:
        previous = observability.capability("ai_provider")
        ok = previous is not None and previous.status is CapabilityStatus.AVAILABLE

    return _reported(
        observability,
        "ai_provider",
        CapabilityStatus.AVAILABLE if ok else CapabilityStatus.UNAVAILABLE,
        "provider_probe_succeeded" if ok else "provider_not_verified",
        provider=settings.ai_provider,
        model=settings.ai_model,
    )


def _reported(
    observability: MLAIObservability,
    name: str,
    status: CapabilityStatus,
    reason: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> OperationalCapability:
    observability.record_capability(name, status, reason)
    observation = observability.capability(name)
    return OperationalCapability(
        status=status,
        reason=reason,
        provider=provider,
        model=model,
        verified_at=observation.verified_at if observation is not None else None,
    )


__all__ = ["build_ml_ai_capability_report"]
