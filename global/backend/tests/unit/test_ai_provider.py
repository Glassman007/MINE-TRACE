from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from pydantic import SecretStr

from app.core.settings import Settings
from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
)
from app.integrations.llm import AIProvider, OpenAIProvider, build_ai_provider
from app.schemas.ai_provider import (
    AIAnalysis,
    AIAnalysisStatus,
    AIClaim,
    AIClaimType,
    AIProviderResultStatus,
)
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    ProvenanceIndexItem,
    SemanticRetrievalMetadata,
)


def _bundle() -> EvidenceBundleResponse:
    incident_id = UUID("10000000-0000-0000-0000-000000000001")
    machine_id = UUID("20000000-0000-0000-0000-000000000001")
    evidence_id = UUID("30000000-0000-0000-0000-000000000001")
    occurred = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)
    item = BundleEvidenceItem(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=None,
        source_type="HUMAN_OBSERVATION",
        original_source_record_id="obs-1",
        original_timestamp=occurred,
        ingestion_timestamp=occurred,
        canonical_event_type="OPERATOR_OBSERVATION",
        canonical_payload={"note": "Hydraulic whine observed under load."},
        raw_source_payload={"note": "Hydraulic whine observed under load."},
        provenance={"source_system": "operator_log"},
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        inclusion_reason="linked to incident",
        relationship_type=IncidentEvidenceRelationshipType.RELATED,
        deterministic_rule_identifier="test.rule",
        similarity_score=None,
        anchor_evidence_id=None,
    )
    provenance = ProvenanceIndexItem(
        evidence_id=evidence_id,
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        source_type="HUMAN_OBSERVATION",
        original_source_record_id="obs-1",
        provenance={"source_system": "operator_log"},
    )
    return EvidenceBundleResponse(
        incident_id=incident_id,
        status=EvidenceBundleStatus.READY,
        primary_incident_evidence=[item],
        selected_exact_history=[],
        selected_semantic_history=[],
        verification_context=[],
        evidence_time_context_snapshots=[],
        provenance_index=[provenance],
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test",
            status_reason="ready",
            incomplete_sections=[],
            truncated_sections=[],
            semantic_retrieval=SemanticRetrievalMetadata(
                configured=False,
                attempted=False,
                failed=False,
                failures=[],
                queried_primary_evidence_ids=[],
            ),
        ),
    )


def _analysis() -> AIAnalysis:
    evidence_id = _bundle().primary_incident_evidence[0].evidence_id
    return AIAnalysis(
        status=AIAnalysisStatus.UNVALIDATED,
        summary="An operator observation records hydraulic noise under load.",
        claims=[
            AIClaim(
                claim_type=AIClaimType.OBSERVATION_RECORDED,
                text="Hydraulic whine was recorded under load.",
                evidence_ids=[evidence_id],
            )
        ],
        limitations=["The supplied bundle does not establish a root cause."],
    )


class FakeResponses:
    def __init__(self, *, output_parsed: object = None, error: Exception | None = None) -> None:
        self.output_parsed = output_parsed
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_parsed=self.output_parsed)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _provider(responses: FakeResponses) -> OpenAIProvider:
    return OpenAIProvider(
        model="configured-model",
        api_key="test-key",
        timeout_seconds=4.0,
        client=FakeClient(responses),
    )


def test_structured_output_parses_but_remains_unvalidated() -> None:
    responses = FakeResponses(output_parsed=_analysis())
    bundle = _bundle()

    result = _provider(responses).analyze(bundle)

    assert result.status is AIProviderResultStatus.UNVALIDATED
    assert result.analysis is not None
    assert result.analysis.status is AIAnalysisStatus.UNVALIDATED
    assert result.analysis.claims[0].claim_type is AIClaimType.OBSERVATION_RECORDED

    request = responses.calls[0]
    assert request["model"] == "configured-model"
    assert request["text_format"] is AIAnalysis
    assert "tools" not in request
    user_input = request["input"][1]["content"]  # type: ignore[index]
    assert str(bundle.incident_id) in user_input
    assert "Hydraulic whine observed under load." in user_input



def test_unknown_citation_is_structurally_parsed_but_never_marked_validated() -> None:
    analysis = _analysis().model_copy(deep=True)
    analysis.claims[0].evidence_ids = [UUID("99999999-0000-0000-0000-000000000999")]

    result = _provider(FakeResponses(output_parsed=analysis)).analyze(_bundle())

    # Provider parsing proves shape only. Membership in the EvidenceBundle is a
    # guard-layer responsibility in the next stage.
    assert result.status is AIProviderResultStatus.UNVALIDATED
    assert result.analysis is not None
    assert result.analysis.status is AIAnalysisStatus.UNVALIDATED

def test_structurally_malformed_output_is_not_accepted() -> None:
    responses = FakeResponses(output_parsed={"status": "UNVALIDATED", "summary": "missing fields"})

    result = _provider(responses).analyze(_bundle())

    assert result.status is AIProviderResultStatus.MALFORMED_RESPONSE
    assert result.analysis is None
    assert result.reason == "structured_output_schema_mismatch"


def test_missing_structured_output_is_malformed() -> None:
    result = _provider(FakeResponses(output_parsed=None)).analyze(_bundle())

    assert result.status is AIProviderResultStatus.MALFORMED_RESPONSE
    assert result.analysis is None


def test_timeout_is_typed_and_does_not_expose_partial_analysis() -> None:
    result = _provider(FakeResponses(error=TimeoutError("slow provider"))).analyze(_bundle())

    assert result.status is AIProviderResultStatus.TIMEOUT
    assert result.analysis is None
    assert result.reason == "provider_timeout"


def test_provider_error_is_typed() -> None:
    result = _provider(FakeResponses(error=RuntimeError("remote error"))).analyze(_bundle())

    assert result.status is AIProviderResultStatus.PROVIDER_ERROR
    assert result.analysis is None


def test_disabled_provider_state_is_valid() -> None:
    provider = build_ai_provider(Settings(ai_enabled=False))

    result = provider.analyze(_bundle())

    assert result.status is AIProviderResultStatus.DISABLED
    assert result.reason == "ai_disabled"


def test_missing_provider_or_model_configuration_is_unavailable() -> None:
    provider = build_ai_provider(Settings(ai_enabled=True, ai_provider=None, ai_model=None))

    result = provider.analyze(_bundle())

    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "missing_provider_or_model_configuration"


def test_unconfigured_openai_provider_is_unavailable_without_crashing() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="openai",
        ai_model="configured-model",
        ai_api_key=None,
    )

    result = build_ai_provider(settings).analyze(_bundle())

    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "missing_ai_api_key"


def test_unsupported_provider_is_unavailable() -> None:
    settings = Settings(
        ai_enabled=True,
        ai_provider="not-selected",
        ai_model="configured-model",
        ai_api_key=SecretStr("secret"),
    )

    result = build_ai_provider(settings).analyze(_bundle())

    assert result.status is AIProviderResultStatus.UNAVAILABLE
    assert result.reason == "unsupported_ai_provider"


def test_factory_builds_selected_openai_adapter_without_external_call() -> None:
    captured: dict[str, object] = {}
    responses = FakeResponses(output_parsed=_analysis())

    def factory(api_key: str, timeout_seconds: float) -> FakeClient:
        captured["api_key"] = api_key
        captured["timeout"] = timeout_seconds
        return FakeClient(responses)

    settings = Settings(
        ai_enabled=True,
        ai_provider="openai",
        ai_model="configured-model",
        ai_api_key=SecretStr("configured-secret"),
        ai_timeout_seconds=7.5,
    )
    provider = build_ai_provider(settings, openai_client_factory=factory)

    assert isinstance(provider, OpenAIProvider)
    assert captured == {"api_key": "configured-secret", "timeout": 7.5}
    assert provider.analyze(_bundle()).status is AIProviderResultStatus.UNVALIDATED


def test_ai_provider_contract_and_openai_adapter_expose_no_mutation_capabilities() -> None:
    assert list(inspect.signature(AIProvider.analyze).parameters) == ["self", "evidence_bundle"]

    forbidden = {
        "close_incident",
        "transition_incident",
        "verify_repair",
        "alter_evidence",
        "update_evidence",
        "alter_owner",
        "alter_severity",
        "acknowledge_handover",
        "establish_recurrence",
        "certify_maintenance",
        "upsert",
        "delete",
        "search",
    }
    public = {
        name
        for name, member in inspect.getmembers(OpenAIProvider)
        if not name.startswith("_") and callable(member)
    }
    assert public == {"analyze", "probe_availability"}
    assert public.isdisjoint(forbidden)
