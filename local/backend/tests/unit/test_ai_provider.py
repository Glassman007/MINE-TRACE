from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from pydantic import SecretStr

from app.core.settings import Settings
from app.domain.enums import EvidenceBundleSourceClassification, EvidenceBundleStatus, IncidentEvidenceRelationshipType
from app.integrations.llm import AIProvider, GroqProvider, build_ai_provider
from app.schemas.ai_provider import AIAnalysis, AIAnalysisStatus, AIClaim, AIClaimType, AIProviderResultStatus
from app.schemas.evidence_bundle import BundleEvidenceItem, EvidenceBundleCompleteness, EvidenceBundleResponse, ProvenanceIndexItem, SemanticRetrievalMetadata


def _bundle() -> EvidenceBundleResponse:
    incident_id = UUID("10000000-0000-0000-0000-000000000001")
    machine_id = UUID("20000000-0000-0000-0000-000000000001")
    evidence_id = UUID("30000000-0000-0000-0000-000000000001")
    occurred = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)
    item = BundleEvidenceItem(
        evidence_id=evidence_id, machine_id=machine_id, component_id=None,
        source_type="HUMAN_OBSERVATION", original_source_record_id="obs-1",
        original_timestamp=occurred, ingestion_timestamp=occurred,
        canonical_event_type="OPERATOR_OBSERVATION",
        canonical_payload={"note": "Hydraulic whine observed under load."},
        raw_source_payload={"note": "Hydraulic whine observed under load."},
        provenance={"source_system": "operator_log"},
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        inclusion_reason="linked to incident", relationship_type=IncidentEvidenceRelationshipType.RELATED,
        deterministic_rule_identifier="test.rule", similarity_score=None, anchor_evidence_id=None,
    )
    return EvidenceBundleResponse(
        incident_id=incident_id, status=EvidenceBundleStatus.READY,
        primary_incident_evidence=[item], selected_exact_history=[], selected_semantic_history=[],
        verification_context=[], evidence_time_context_snapshots=[],
        provenance_index=[ProvenanceIndexItem(
            evidence_id=evidence_id,
            source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
            source_type="HUMAN_OBSERVATION", original_source_record_id="obs-1",
            provenance={"source_system": "operator_log"},
        )],
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test", status_reason="ready", incomplete_sections=[],
            truncated_sections=[], semantic_retrieval=SemanticRetrievalMetadata(
                configured=False, attempted=False, failed=False, failures=[], queried_primary_evidence_ids=[]
            ),
        ),
    )


def _analysis() -> AIAnalysis:
    evidence_id = _bundle().primary_incident_evidence[0].evidence_id
    return AIAnalysis(
        status=AIAnalysisStatus.UNVALIDATED,
        summary="An operator observation records hydraulic noise under load.",
        claims=[AIClaim(
            claim_type=AIClaimType.OBSERVATION_RECORDED,
            text="Hydraulic whine was recorded under load.", evidence_ids=[evidence_id],
        )],
        limitations=["The supplied bundle does not establish a root cause."],
    )


class FakeCompletions:
    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict[str, object]] = []
    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeModels:
    def retrieve(self, model: str) -> object:
        return {"id": model}


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)
        self.models = FakeModels()


class StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status={status_code}")
        self.status_code = status_code


def _provider(completions: FakeCompletions) -> GroqProvider:
    return GroqProvider(model="configured-model", api_key="test-key", timeout_seconds=4.0, client=FakeClient(completions))


def _json(analysis: AIAnalysis) -> str:
    return json.dumps(analysis.model_dump(mode="json"))


def test_successful_groq_response_is_structured_but_unvalidated() -> None:
    completions = FakeCompletions(content=_json(_analysis()))
    bundle = _bundle()
    result = _provider(completions).analyze(bundle)
    assert result.status is AIProviderResultStatus.UNVALIDATED
    assert result.analysis is not None
    assert result.analysis.claims[0].evidence_ids == [bundle.primary_incident_evidence[0].evidence_id]
    request = completions.calls[0]
    assert request["model"] == "configured-model"
    assert request["response_format"] == {"type": "json_object"}
    assert request["temperature"] == 0
    assert "tools" not in request
    assert str(bundle.incident_id) in request["messages"][1]["content"]  # type: ignore[index]


def test_unknown_citation_remains_for_independent_guard_to_reject() -> None:
    analysis = _analysis().model_copy(deep=True)
    analysis.claims[0].evidence_ids = [UUID("99999999-0000-0000-0000-000000000999")]
    result = _provider(FakeCompletions(content=_json(analysis))).analyze(_bundle())
    assert result.status is AIProviderResultStatus.UNVALIDATED


def test_malformed_groq_response_degrades() -> None:
    result = _provider(FakeCompletions(content='{"status":"UNVALIDATED","summary":"missing"}')).analyze(_bundle())
    assert result.status is AIProviderResultStatus.MALFORMED_RESPONSE
    assert result.reason == "structured_output_schema_mismatch"


def test_missing_groq_content_degrades() -> None:
    result = _provider(FakeCompletions(content=None)).analyze(_bundle())
    assert result.status is AIProviderResultStatus.MALFORMED_RESPONSE
    assert result.reason == "missing_structured_output"


def test_groq_timeout_degrades() -> None:
    result = _provider(FakeCompletions(error=TimeoutError("slow"))).analyze(_bundle())
    assert result.status is AIProviderResultStatus.TIMEOUT
    assert result.reason == "provider_timeout"


def test_invalid_groq_api_key_degrades() -> None:
    result = _provider(FakeCompletions(error=StatusError(401))).analyze(_bundle())
    assert result.status is AIProviderResultStatus.PROVIDER_ERROR
    assert result.reason == "invalid_api_key"


def test_groq_rate_limit_degrades() -> None:
    result = _provider(FakeCompletions(error=StatusError(429))).analyze(_bundle())
    assert result.status is AIProviderResultStatus.PROVIDER_ERROR
    assert result.reason == "rate_limited"


def test_groq_unavailable_degrades() -> None:
    result = _provider(FakeCompletions(error=RuntimeError("network unavailable"))).analyze(_bundle())
    assert result.status is AIProviderResultStatus.PROVIDER_ERROR
    assert result.reason == "provider_error"


def test_disabled_provider_state_is_valid() -> None:
    result = build_ai_provider(Settings(ai_enabled=False)).analyze(_bundle())
    assert result.status is AIProviderResultStatus.DISABLED


def test_no_groq_key_configured_is_unavailable() -> None:
    settings = Settings(ai_enabled=True, ai_provider="groq", ai_model="configured-model", groq_api_key=None)
    result = build_ai_provider(settings).analyze(_bundle())
    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "missing_groq_api_key"


def test_unsupported_provider_is_unavailable() -> None:
    settings = Settings(ai_enabled=True, ai_provider="not-selected", ai_model="configured-model", groq_api_key=SecretStr("secret"))
    result = build_ai_provider(settings).analyze(_bundle())
    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "unsupported_ai_provider"


def test_factory_builds_native_groq_adapter_without_external_call() -> None:
    captured: dict[str, object] = {}
    completions = FakeCompletions(content=_json(_analysis()))
    def factory(api_key: str, timeout_seconds: float) -> FakeClient:
        captured["api_key"] = api_key
        captured["timeout"] = timeout_seconds
        return FakeClient(completions)
    settings = Settings(
        ai_enabled=True, ai_provider="groq", ai_model="configured-model",
        groq_api_key=SecretStr("configured-secret"), ai_timeout_seconds=7.5,
    )
    provider = build_ai_provider(settings, groq_client_factory=factory)
    assert isinstance(provider, GroqProvider)
    assert captured == {"api_key": "configured-secret", "timeout": 7.5}
    assert provider.analyze(_bundle()).status is AIProviderResultStatus.UNVALIDATED


def test_groq_adapter_exposes_no_mutation_capabilities() -> None:
    assert list(inspect.signature(AIProvider.analyze).parameters) == ["self", "evidence_bundle"]
    public = {name for name, member in inspect.getmembers(GroqProvider) if not name.startswith("_") and callable(member)}
    assert public == {"analyze", "probe_availability"}


def test_factory_degrades_when_groq_client_cannot_be_constructed() -> None:
    def broken_factory(api_key: str, timeout_seconds: float):
        del api_key, timeout_seconds
        raise ModuleNotFoundError("groq")
    settings = Settings(
        ai_enabled=True, ai_provider="groq", ai_model="configured-model",
        groq_api_key=SecretStr("configured-secret"),
    )
    result = build_ai_provider(settings, groq_client_factory=broken_factory).analyze(_bundle())
    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "provider_unavailable"
