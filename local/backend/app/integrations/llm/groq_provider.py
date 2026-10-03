"""Groq chat-completions adapter for advisory MINE-TRACE analysis.

The adapter has no tools and receives only a sealed deterministic EvidenceBundle.
It requests JSON, validates it with Pydantic, and never owns canonical mutation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.integrations.llm.base import AIProvider
from app.schemas.ai_provider import AIAnalysis, AIProviderResult, AIProviderResultStatus
from app.schemas.evidence_bundle import EvidenceBundleResponse


class _CompletionsAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ChatAPI(Protocol):
    completions: _CompletionsAPI


class _ModelsAPI(Protocol):
    def retrieve(self, model: str) -> Any: ...


class _GroqClientLike(Protocol):
    chat: _ChatAPI
    models: _ModelsAPI


ClientFactory = Callable[[str, float], _GroqClientLike]


_PROVIDER_INSTRUCTIONS = """You are the optional advisory analysis layer for MINE-TRACE.
Use ONLY the supplied EvidenceBundle JSON. Never infer hidden database state, never
request tools or external data, and never make authoritative safety, verification,
incident, synchronization, or maintenance decisions. Return exactly one JSON object
matching this schema:
{
  "status": "UNVALIDATED",
  "summary": "string",
  "claims": [
    {
      "claim_type": "OBSERVATION_RECORDED|EXACT_HISTORY_PATTERN|SEMANTIC_SIMILARITY|VERIFICATION_CONTEXT|LIMITATION",
      "text": "string",
      "evidence_ids": ["uuid", "..."]
    }
  ],
  "limitations": ["string", "..."]
}
Every factual claim must cite one or more evidence_id values present in the supplied
bundle. Preserve evidence identifiers exactly. Do not claim semantic similarity proves
the same root cause. Do not instruct MINE-TRACE to mutate incidents, evidence,
verification, return-to-service, synchronization, ownership, severity, recurrence, or
maintenance certification. State material uncertainty in limitations.
"""


def _default_client_factory(api_key: str, timeout_seconds: float) -> _GroqClientLike:
    # Lazy import keeps the deterministic backend importable when AI is disabled.
    from groq import Groq

    return Groq(api_key=api_key, timeout=timeout_seconds)


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _is_timeout_exception(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ in {
        "APITimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutException",
    }


def _completion_content(response: Any) -> str | None:
    choices = getattr(response, "choices", None)
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content if isinstance(content, str) and content.strip() else None


class GroqProvider(AIProvider):
    """Native Groq SDK adapter returning strictly validated advisory JSON."""

    provider_name = "groq"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: float,
        client: _GroqClientLike | None = None,
        client_factory: ClientFactory = _default_client_factory,
        observability: MLAIObservability | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._model = model.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._client = client or client_factory(api_key, self._timeout_seconds)
        self._observability = observability or get_ml_ai_observability()

    def probe_availability(self) -> bool:
        retrieve = getattr(getattr(self._client, "models", None), "retrieve", None)
        if not callable(retrieve):
            return False
        try:
            retrieve(self._model)
        except Exception as exc:
            reason = "provider_timeout" if _is_timeout_exception(exc) else "provider_probe_failed"
            self._observability.record_capability(
                "ai_provider", CapabilityStatus.UNAVAILABLE, reason
            )
            return False
        self._observability.record_capability(
            "ai_provider", CapabilityStatus.AVAILABLE, "provider_probe_succeeded"
        )
        return True

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        bundle_json = json.dumps(
            evidence_bundle.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _PROVIDER_INSTRUCTIONS},
                    {"role": "user", "content": bundle_json},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = _completion_content(response)
            if content is None:
                return AIProviderResult(
                    status=AIProviderResultStatus.MALFORMED_RESPONSE,
                    analysis=None,
                    reason="missing_structured_output",
                )
            try:
                parsed_json = json.loads(content)
                parsed = AIAnalysis.model_validate(parsed_json)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
                return AIProviderResult(
                    status=AIProviderResultStatus.MALFORMED_RESPONSE,
                    analysis=None,
                    reason="structured_output_schema_mismatch",
                )
        except Exception as exc:
            if _is_timeout_exception(exc):
                self._observability.record_capability(
                    "ai_provider", CapabilityStatus.UNAVAILABLE, "provider_timeout"
                )
                return AIProviderResult(
                    status=AIProviderResultStatus.TIMEOUT,
                    analysis=None,
                    reason="provider_timeout",
                )
            code = _status_code(exc)
            if code == 401:
                reason = "invalid_api_key"
            elif code == 429:
                reason = "rate_limited"
            else:
                reason = "provider_error"
            self._observability.record_capability(
                "ai_provider", CapabilityStatus.UNAVAILABLE, reason
            )
            return AIProviderResult(
                status=AIProviderResultStatus.PROVIDER_ERROR,
                analysis=None,
                reason=reason,
            )

        self._observability.record_capability(
            "ai_provider", CapabilityStatus.AVAILABLE, "provider_request_succeeded"
        )
        return AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=parsed,
            reason=None,
        )


__all__ = ["GroqProvider"]
