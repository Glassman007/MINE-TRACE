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


class _ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _Chat(Protocol):
    completions: _ChatCompletions


class _GroqClientLike(Protocol):
    chat: _Chat


ClientFactory = Callable[[str, float], _GroqClientLike]

_SYSTEM = """You are the optional advisory fleet-analysis layer for MINE-TRACE.
Use ONLY the supplied canonical context. Do not use tools or outside knowledge.
Do not mutate or decide incident state, verification, maintenance truth,
synchronization, recurrence, or return-to-service. Do not invent metrics.
Return JSON matching this shape exactly: {\"status\":\"UNVALIDATED\",\"summary\":str,
\"claims\":[{\"claim_type\": one of EVENT_OCCURRED,OBSERVATION_RECORDED,
MAINTENANCE_RECORDED,VERIFICATION_STARTED,VERIFICATION_PASSED,VERIFICATION_FAILED,
RECURRENCE_RECORDED,SIMILAR_HISTORY_FOUND,CONTEXT_RECORDED,STATUS_REPORTED,
\"text\":str,\"evidence_ids\":[uuid,...]}],\"limitations\":[str,...]}.
Every factual claim must cite evidence_id values present in the supplied context.
Similarity is retrieval ranking only, never confidence, probability, or proof.
"""


def _default_factory(api_key: str, timeout_seconds: float) -> _GroqClientLike:
    from groq import Groq
    return Groq(api_key=api_key, timeout=timeout_seconds, max_retries=0)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or type(exc).__name__ in {"APITimeoutError", "ConnectTimeout", "ReadTimeout", "TimeoutException"}


class GroqProvider(AIProvider):
    provider_name = "groq"

    def __init__(self, *, model: str, api_key: str, timeout_seconds: float, client: _GroqClientLike | None = None, client_factory: ClientFactory = _default_factory, observability: MLAIObservability | None = None) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if not api_key.strip():
            raise ValueError("api_key must not be blank")
        self._model = model.strip()
        self._client = client or client_factory(api_key, float(timeout_seconds))
        self._observability = observability or get_ml_ai_observability()

    @property
    def model(self) -> str:
        return self._model

    def probe_availability(self) -> bool:
        # Avoid generating content during readiness checks. Groq SDK model listing
        # is optional for injected test clients, so a configured client is treated
        # as unverified until an explicit analysis call succeeds.
        return False

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        return self._analyze_payload({"evidence_bundle": evidence_bundle.model_dump(mode="json")})

    def analyze_fleet(self, *, user_request: str, canonical_context: dict[str, Any]) -> AIProviderResult:
        return self._analyze_payload({"user_request": user_request, "canonical_context": canonical_context})

    def _analyze_payload(self, payload: dict[str, Any]) -> AIProviderResult:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": json.dumps(payload, sort_keys=True, separators=(",", ":"))},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("missing response content")
            parsed = AIAnalysis.model_validate_json(content)
            self._observability.record_capability("ai_provider", CapabilityStatus.AVAILABLE, "groq_request_succeeded")
            return AIProviderResult(status=AIProviderResultStatus.UNVALIDATED, analysis=parsed)
        except ValidationError:
            return AIProviderResult(status=AIProviderResultStatus.MALFORMED_RESPONSE, reason="invalid_structured_output")
        except Exception as exc:
            if _is_timeout(exc):
                return AIProviderResult(status=AIProviderResultStatus.TIMEOUT, reason="groq_timeout")
            name = type(exc).__name__
            reason = "groq_quota_or_rate_limited" if name in {"RateLimitError"} else f"groq_provider_error:{name}"
            return AIProviderResult(status=AIProviderResultStatus.PROVIDER_ERROR, reason=reason)
