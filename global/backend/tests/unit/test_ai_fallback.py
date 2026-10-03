from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
)
from app.integrations.llm import build_ai_provider
from app.schemas.ai_provider import (
    AIAnalysis,
    AIAnalysisStatus,
    AIClaim,
    AIClaimType,
    AIProviderResult,
    AIProviderResultStatus,
)
from app.schemas.ai_result import (
    AIAnalysisFallbackReason,
    AIAnalysisResultType,
    SemanticEnrichmentState,
)
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    ProvenanceIndexItem,
    SemanticRetrievalMetadata,
)
from app.schemas.semantic_history import SemanticHistoryFailure
from app.services.ai_analysis_pipeline import AIAnalysisPipeline


INCIDENT_ID = UUID("10000000-0000-0000-0000-000000000001")
MACHINE_ID = UUID("20000000-0000-0000-0000-000000000001")
EVIDENCE_ID = UUID("30000000-0000-0000-0000-000000000001")
OUTSIDE_ID = UUID("99999999-0000-0000-0000-000000000999")
OCCURRED = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    status: EvidenceBundleStatus = EvidenceBundleStatus.READY,
    semantic_configured: bool = False,
    semantic_attempted: bool = False,
    semantic_failed: bool = False,
) -> EvidenceBundleResponse:
    primary = []
    provenance = []
    if status is not EvidenceBundleStatus.INSUFFICIENT_EVIDENCE:
        item = BundleEvidenceItem(
            evidence_id=EVIDENCE_ID,
            machine_id=MACHINE_ID,
            component_id=None,
            source_type="HUMAN_OBSERVATION",
            original_source_record_id="obs-1",
            original_timestamp=OCCURRED,
            ingestion_timestamp=OCCURRED,
            canonical_event_type="OPERATOR_OBSERVATION",
            canonical_payload={"note": "Hydraulic whine observed under load."},
            raw_source_payload={"note": "Hydraulic whine observed under load."},
            provenance={"source_system": "operator_log"},
            source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
            inclusion_reason="linked to incident",
            relationship_type=IncidentEvidenceRelationshipType.RELATED,
            deterministic_rule_identifier="test.rule",
        )
        primary = [item]
        provenance = [
            ProvenanceIndexItem(
                evidence_id=EVIDENCE_ID,
                source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
                source_type="HUMAN_OBSERVATION",
                original_source_record_id="obs-1",
                provenance={"source_system": "operator_log"},
            )
        ]

    return EvidenceBundleResponse(
        incident_id=INCIDENT_ID,
        status=status,
        primary_incident_evidence=primary,
        selected_exact_history=[],
        selected_semantic_history=[],
        verification_context=[],
        evidence_time_context_snapshots=[],
        provenance_index=provenance,
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test",
            status_reason="test",
            incomplete_sections=[],
            truncated_sections=[],
            semantic_retrieval=SemanticRetrievalMetadata(
                configured=semantic_configured,
                attempted=semantic_attempted,
                failed=semantic_failed,
                failures=(
                    [SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE]
                    if semantic_failed
                    else []
                ),
                queried_primary_evidence_ids=[],
            ),
        ),
    )


def _analysis(*, evidence_id: UUID = EVIDENCE_ID, text: str = "An observation was recorded.") -> AIAnalysis:
    return AIAnalysis(
        status=AIAnalysisStatus.UNVALIDATED,
        summary="The supplied evidence records an operator observation.",
        claims=[
            AIClaim(
                claim_type=AIClaimType.OBSERVATION_RECORDED,
                text=text,
                evidence_ids=[evidence_id],
            )
        ],
        limitations=["The bundle does not establish a root cause."],
    )


class StaticProvider:
    def __init__(self, result: AIProviderResult) -> None:
        self.result = result
        self.calls = 0

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        self.calls += 1
        return self.result


class MustNotBeCalled:
    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        raise AssertionError("provider must not be called for insufficient evidence")


def _fallback_reason(provider: StaticProvider, bundle: EvidenceBundleResponse | None = None):
    result = AIAnalysisPipeline(provider).analyze(bundle or _bundle())
    assert result.result_type is AIAnalysisResultType.FALLBACK
    assert result.validated_ai is None
    assert result.fallback is not None
    return result.fallback.reason


def test_ai_disabled_uses_deterministic_fallback() -> None:
    provider = build_ai_provider(Settings(ai_enabled=False))
    result = AIAnalysisPipeline(provider).analyze(_bundle())

    assert result.result_type is AIAnalysisResultType.FALLBACK
    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.AI_DISABLED


def test_provider_not_configured_uses_fallback() -> None:
    provider = build_ai_provider(Settings(ai_enabled=True, ai_provider=None, ai_model=None))
    result = AIAnalysisPipeline(provider).analyze(_bundle())

    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.AI_PROVIDER_NOT_CONFIGURED


def test_provider_unavailable_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.UNAVAILABLE, reason="provider_offline")
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.AI_PROVIDER_UNAVAILABLE


def test_provider_error_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.PROVIDER_ERROR, reason="provider_error")
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.AI_PROVIDER_ERROR


def test_timeout_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.TIMEOUT, reason="provider_timeout")
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.AI_TIMEOUT


def test_malformed_model_output_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(
            status=AIProviderResultStatus.MALFORMED_RESPONSE,
            reason="structured_output_schema_mismatch",
        )
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.MALFORMED_OUTPUT


def test_unknown_citation_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=_analysis(evidence_id=OUTSIDE_ID),
        )
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.UNKNOWN_CITATION


def test_prohibited_claim_uses_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=_analysis(text="The proven root cause is pump cavitation."),
        )
    )
    assert _fallback_reason(provider) is AIAnalysisFallbackReason.PROHIBITED_CLAIM


def test_insufficient_evidence_falls_back_without_calling_provider() -> None:
    result = AIAnalysisPipeline(MustNotBeCalled()).analyze(
        _bundle(status=EvidenceBundleStatus.INSUFFICIENT_EVIDENCE)
    )

    assert result.result_type is AIAnalysisResultType.FALLBACK
    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.INSUFFICIENT_EVIDENCE


def test_qdrant_unavailable_is_reported_without_semantic_results() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.DISABLED, reason="ai_disabled")
    )
    result = AIAnalysisPipeline(provider).analyze(
        _bundle(
            semantic_configured=True,
            semantic_attempted=True,
            semantic_failed=True,
        )
    )

    assert result.fallback is not None
    semantic = result.fallback.semantic_history
    assert semantic.state is SemanticEnrichmentState.UNAVAILABLE
    assert semantic.selected_match_count == 0
    assert semantic.failure_reasons == ["SEMANTIC_INDEX_UNAVAILABLE"]


def test_semantic_disabled_is_reported_honestly() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.DISABLED, reason="ai_disabled")
    )
    result = AIAnalysisPipeline(provider).analyze(_bundle())

    assert result.fallback is not None
    assert result.fallback.semantic_history.state is SemanticEnrichmentState.DISABLED
    assert result.fallback.semantic_history.selected_match_count == 0


def test_fallback_contains_only_deterministic_bundle_facts() -> None:
    provider = StaticProvider(
        AIProviderResult(status=AIProviderResultStatus.TIMEOUT, reason="some remote text")
    )
    result = AIAnalysisPipeline(provider).analyze(_bundle())

    assert result.fallback is not None
    fact = result.fallback.primary_evidence[0]
    assert fact.evidence_id == EVIDENCE_ID
    assert fact.original_timestamp == OCCURRED
    assert fact.canonical_payload == {"note": "Hydraulic whine observed under load."}
    assert fact.provenance == {"source_system": "operator_log"}
    assert "remote" not in result.fallback.reason_detail.lower()


def test_validated_candidate_is_distinct_from_fallback() -> None:
    provider = StaticProvider(
        AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=_analysis(),
        )
    )
    result = AIAnalysisPipeline(provider).analyze(_bundle())

    assert result.result_type is AIAnalysisResultType.VALIDATED_AI
    assert result.fallback is None
    assert result.validated_ai is not None
    assert result.validated_ai.status == "VALIDATED"


@pytest.mark.parametrize(
    "reason",
    list(AIAnalysisFallbackReason),
)
def test_fallback_reason_has_stable_deterministic_detail(reason: AIAnalysisFallbackReason) -> None:
    from app.services.ai_fallback import DeterministicFallbackBuilder

    first = DeterministicFallbackBuilder().build(_bundle(), reason)
    second = DeterministicFallbackBuilder().build(_bundle(), reason)
    assert first == second

class RaisingTimeoutProvider:
    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        raise TimeoutError("transport escaped adapter")


class RaisingErrorProvider:
    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        raise RuntimeError("transport escaped adapter")


def test_unexpected_provider_timeout_cannot_escape_fallback_boundary() -> None:
    result = AIAnalysisPipeline(RaisingTimeoutProvider()).analyze(_bundle())
    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.AI_TIMEOUT


def test_unexpected_provider_error_cannot_escape_fallback_boundary() -> None:
    result = AIAnalysisPipeline(RaisingErrorProvider()).analyze(_bundle())
    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.AI_PROVIDER_ERROR


def test_observability_captures_ai_timeout_error_and_rejection_stages() -> None:
    timeout_observer = MLAIObservability()
    timeout_result = AIAnalysisPipeline(
        StaticProvider(
            AIProviderResult(
                status=AIProviderResultStatus.TIMEOUT, reason="provider_timeout"
            )
        ),
        observability=timeout_observer,
    ).analyze(_bundle())
    assert timeout_result.fallback is not None
    timeout_signals = timeout_observer.snapshot()
    assert timeout_signals.ai_provider_timeouts == 1
    assert timeout_signals.fallback_reasons["AI_TIMEOUT"] == 1

    error_observer = MLAIObservability()
    AIAnalysisPipeline(
        StaticProvider(
            AIProviderResult(
                status=AIProviderResultStatus.PROVIDER_ERROR, reason="provider_error"
            )
        ),
        observability=error_observer,
    ).analyze(_bundle())
    assert error_observer.snapshot().ai_provider_errors == 1

    schema_observer = MLAIObservability()
    AIAnalysisPipeline(
        StaticProvider(
            AIProviderResult(
                status=AIProviderResultStatus.MALFORMED_RESPONSE,
                reason="structured_output_schema_mismatch",
            )
        ),
        observability=schema_observer,
    ).analyze(_bundle())
    assert schema_observer.snapshot().ai_schema_rejections == 1

    citation_observer = MLAIObservability()
    AIAnalysisPipeline(
        StaticProvider(
            AIProviderResult(
                status=AIProviderResultStatus.UNVALIDATED,
                analysis=_analysis(evidence_id=OUTSIDE_ID),
            )
        ),
        observability=citation_observer,
    ).analyze(_bundle())
    assert citation_observer.snapshot().ai_citation_rejections == 1

    policy_observer = MLAIObservability()
    AIAnalysisPipeline(
        StaticProvider(
            AIProviderResult(
                status=AIProviderResultStatus.UNVALIDATED,
                analysis=_analysis(text="The proven root cause is pump cavitation."),
            )
        ),
        observability=policy_observer,
    ).analyze(_bundle())
    assert policy_observer.snapshot().ai_claim_policy_rejections == 1
