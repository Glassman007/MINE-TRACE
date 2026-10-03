"""Typed operational capability reporting for optional ML/AI infrastructure."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.capabilities import CapabilityStatus


class OperationalCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CapabilityStatus
    reason: str | None = None
    provider: str | None = None
    model: str | None = None
    verified_at: datetime | None = None


class MLAIOperationalSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qdrant_connectivity_failures: int = Field(ge=0)
    qdrant_search_count: int = Field(ge=0)
    qdrant_search_failures: int = Field(ge=0)
    last_qdrant_search_latency_ms: float | None = Field(default=None, ge=0)
    embedding_provider_failures: int = Field(ge=0)
    embedding_provider_successes: int = Field(ge=0)
    indexing_failures: int = Field(ge=0)
    stale_qdrant_reference_count: int = Field(ge=0)
    ai_provider_timeouts: int = Field(ge=0)
    ai_provider_errors: int = Field(ge=0)
    ai_provider_successes: int = Field(ge=0)
    ai_schema_rejections: int = Field(ge=0)
    ai_citation_rejections: int = Field(ge=0)
    ai_claim_policy_rejections: int = Field(ge=0)
    fallback_reasons: dict[str, int]


class MLAICapabilityReport(BaseModel):
    """Operational status only; canonical application health remains separate."""

    model_config = ConfigDict(extra="forbid")

    qdrant_semantic: OperationalCapability
    embedding_provider: OperationalCapability
    ai_provider: OperationalCapability
    signals: MLAIOperationalSignals


__all__ = [
    "MLAICapabilityReport",
    "MLAIOperationalSignals",
    "OperationalCapability",
]
