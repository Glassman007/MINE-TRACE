"""Non-authoritative runtime observability for optional ML/AI integrations.

This module stores process-local operational signals only. It never persists
canonical domain state and never records evidence payloads, provenance bodies,
API keys, authorization headers, prompts, or model response text.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Mapping

from app.core.capabilities import CapabilityStatus


@dataclass(frozen=True, slots=True)
class CapabilityObservation:
    status: CapabilityStatus
    reason: str | None
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class MLAIObservabilitySnapshot:
    qdrant_connectivity_failures: int
    qdrant_search_count: int
    qdrant_search_failures: int
    last_qdrant_search_latency_ms: float | None
    embedding_provider_failures: int
    embedding_provider_successes: int
    indexing_failures: int
    stale_qdrant_reference_count: int
    ai_provider_timeouts: int
    ai_provider_errors: int
    ai_provider_successes: int
    ai_schema_rejections: int
    ai_citation_rejections: int
    ai_claim_policy_rejections: int
    fallback_reasons: Mapping[str, int]


class MLAIObservability:
    """Thread-safe, process-local operational telemetry.

    Signal values are deliberately coarse. Arbitrary payloads are not accepted,
    which prevents this class from becoming a side channel for canonical or
    secret data.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[str] = Counter()
        self._fallback_reasons: Counter[str] = Counter()
        self._last_qdrant_search_latency_ms: float | None = None
        self._capabilities: dict[str, CapabilityObservation] = {}

    def record_capability(
        self,
        capability: str,
        status: CapabilityStatus,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            self._capabilities[capability] = CapabilityObservation(
                status=status,
                reason=reason,
                verified_at=datetime.now(UTC),
            )

    def capability(self, capability: str) -> CapabilityObservation | None:
        with self._lock:
            return self._capabilities.get(capability)

    def record_qdrant_connectivity_failure(self) -> None:
        self._increment("qdrant_connectivity_failures")

    def record_qdrant_search(self, *, latency_ms: float, succeeded: bool) -> None:
        with self._lock:
            self._counters["qdrant_search_count"] += 1
            if not succeeded:
                self._counters["qdrant_search_failures"] += 1
            self._last_qdrant_search_latency_ms = round(max(0.0, latency_ms), 3)

    def record_embedding_success(self) -> None:
        self._increment("embedding_provider_successes")

    def record_embedding_failure(self) -> None:
        self._increment("embedding_provider_failures")

    def record_indexing_failure(self, count: int = 1) -> None:
        self._increment("indexing_failures", count)

    def record_stale_qdrant_reference(self, count: int = 1) -> None:
        self._increment("stale_qdrant_reference_count", count)

    def record_ai_provider_success(self) -> None:
        self._increment("ai_provider_successes")

    def record_ai_provider_timeout(self) -> None:
        self._increment("ai_provider_timeouts")

    def record_ai_provider_error(self) -> None:
        self._increment("ai_provider_errors")

    def record_ai_rejection(self, stage: str) -> None:
        normalized = stage.strip().upper()
        mapping = {
            "SCHEMA_VALIDATION": "ai_schema_rejections",
            "CITATION_ID_VALIDATION": "ai_citation_rejections",
            "CLAIM_POLICY_VALIDATION": "ai_claim_policy_rejections",
        }
        counter = mapping.get(normalized)
        if counter is not None:
            self._increment(counter)

    def record_fallback(self, reason: str) -> None:
        normalized = reason.strip().upper() or "UNKNOWN"
        with self._lock:
            self._fallback_reasons[normalized] += 1

    def snapshot(self) -> MLAIObservabilitySnapshot:
        with self._lock:
            return MLAIObservabilitySnapshot(
                qdrant_connectivity_failures=self._counters[
                    "qdrant_connectivity_failures"
                ],
                qdrant_search_count=self._counters["qdrant_search_count"],
                qdrant_search_failures=self._counters["qdrant_search_failures"],
                last_qdrant_search_latency_ms=self._last_qdrant_search_latency_ms,
                embedding_provider_failures=self._counters[
                    "embedding_provider_failures"
                ],
                embedding_provider_successes=self._counters[
                    "embedding_provider_successes"
                ],
                indexing_failures=self._counters["indexing_failures"],
                stale_qdrant_reference_count=self._counters[
                    "stale_qdrant_reference_count"
                ],
                ai_provider_timeouts=self._counters["ai_provider_timeouts"],
                ai_provider_errors=self._counters["ai_provider_errors"],
                ai_provider_successes=self._counters["ai_provider_successes"],
                ai_schema_rejections=self._counters["ai_schema_rejections"],
                ai_citation_rejections=self._counters["ai_citation_rejections"],
                ai_claim_policy_rejections=self._counters[
                    "ai_claim_policy_rejections"
                ],
                fallback_reasons=dict(sorted(self._fallback_reasons.items())),
            )

    def _increment(self, key: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._counters[key] += count


_default_observability = MLAIObservability()


def get_ml_ai_observability() -> MLAIObservability:
    """Return the process-local default recorder used outside app injection."""

    return _default_observability


__all__ = [
    "CapabilityObservation",
    "MLAIObservability",
    "MLAIObservabilitySnapshot",
    "get_ml_ai_observability",
]
