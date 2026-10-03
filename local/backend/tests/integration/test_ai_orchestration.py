from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import create_database_engine, get_db_session
from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
)
from app.integrations.llm import LLMProviderUnavailableError
from app.main import app
from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord, IncidentRecord, MachineRecord
from app.schemas.ai_analysis import AIAnalysisStatus, AIFallbackReason
from app.schemas.ai_provider import (
    AIAnalysis as ProviderAIAnalysis,
    AIClaim,
    AIClaimType,
    AIProviderResult,
    AIProviderResultStatus,
)
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    ProvenanceIndexItem,
    SemanticRetrievalMetadata,
)
from app.services.ai_orchestration import AIOrchestrationService


def _bundle() -> EvidenceBundleResponse:
    incident_id = UUID("10000000-0000-0000-0000-000000000001")
    machine_id = UUID("20000000-0000-0000-0000-000000000001")
    evidence_id = UUID("30000000-0000-0000-0000-000000000001")
    occurred = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    item = BundleEvidenceItem(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=None,
        source_type="MACHINE_EVENT",
        original_source_record_id="evt-1",
        original_timestamp=occurred,
        ingestion_timestamp=occurred,
        canonical_event_type="HYDRAULIC_WARNING",
        canonical_payload={"pressure": 91},
        raw_source_payload={"raw_pressure": 91},
        provenance={"source_system": "ecu"},
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        inclusion_reason="active incident evidence",
        relationship_type=IncidentEvidenceRelationshipType.RELATED,
        deterministic_rule_identifier="test.rule",
    )
    return EvidenceBundleResponse(
        incident_id=incident_id,
        status=EvidenceBundleStatus.READY,
        primary_incident_evidence=[item],
        selected_exact_history=[],
        selected_semantic_history=[],
        verification_context=[],
        evidence_time_context_snapshots=[],
        provenance_index=[
            ProvenanceIndexItem(
                evidence_id=evidence_id,
                source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
                source_type="MACHINE_EVENT",
                original_source_record_id="evt-1",
                provenance={"source_system": "ecu"},
            )
        ],
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test canonical policy",
            status_reason="canonical primary evidence is usable",
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


def _valid_output(evidence_id: UUID, *, summary: str = "Hydraulic pressure warning is present.") -> str:
    return json.dumps(
        {
            "summary": {
                "text": summary,
                "evidence_ids": [str(evidence_id)],
            },
            "relevant_observations": [
                {
                    "text": "The primary evidence reports the warning.",
                    "evidence_ids": [str(evidence_id)],
                }
            ],
            "possible_historical_similarities": [],
            "unresolved_contradictions": [],
            "evidence_references": [str(evidence_id)],
        }
    )


class CapturingProvider:
    def __init__(self, output: str):
        self.output = output
        self.received: list[EvidenceBundleResponse] = []

    def generate_analysis(self, evidence_bundle: EvidenceBundleResponse) -> str:
        self.received.append(evidence_bundle)
        return self.output


class TimeoutProvider:
    def generate_analysis(self, evidence_bundle: EvidenceBundleResponse) -> str:
        raise TimeoutError("provider timeout")


class UnavailableProvider:
    def generate_analysis(self, evidence_bundle: EvidenceBundleResponse) -> str:
        raise LLMProviderUnavailableError("offline")


class GenericFailureProvider:
    def generate_analysis(self, evidence_bundle: EvidenceBundleResponse) -> str:
        raise RuntimeError("provider failure")


def test_validated_output_and_provider_receives_only_bundle() -> None:
    bundle = _bundle()
    evidence_id = bundle.primary_incident_evidence[0].evidence_id
    provider = CapturingProvider(_valid_output(evidence_id))

    result = AIOrchestrationService(provider).analyze(bundle)

    assert result.status is AIAnalysisStatus.VALIDATED
    assert result.fallback_reason is None
    assert result.analysis is not None
    assert result.analysis.evidence_references == [evidence_id]
    assert provider.received == [bundle]


def test_llm_missing_returns_deterministic_fallback() -> None:
    bundle = _bundle()
    first = AIOrchestrationService(None).analyze(bundle)
    second = AIOrchestrationService(None).analyze(bundle)

    assert first == second
    assert first.status is AIAnalysisStatus.FALLBACK
    assert first.analysis is None
    assert first.fallback_reason is AIFallbackReason.LLM_UNAVAILABLE


def test_llm_unavailable_returns_fallback() -> None:
    result = AIOrchestrationService(UnavailableProvider()).analyze(_bundle())
    assert result.fallback_reason is AIFallbackReason.LLM_UNAVAILABLE


def test_timeout_returns_fallback() -> None:
    result = AIOrchestrationService(TimeoutProvider()).analyze(_bundle())
    assert result.fallback_reason is AIFallbackReason.LLM_TIMEOUT


def test_generic_provider_failure_returns_fallback() -> None:
    result = AIOrchestrationService(GenericFailureProvider()).analyze(_bundle())
    assert result.fallback_reason is AIFallbackReason.LLM_ERROR


def test_invalid_json_returns_fallback() -> None:
    result = AIOrchestrationService(CapturingProvider("not-json")).analyze(_bundle())
    assert result.fallback_reason is AIFallbackReason.INVALID_JSON


def test_malformed_llm_schema_returns_fallback() -> None:
    malformed = json.dumps({"summary": "not a cited claim"})
    result = AIOrchestrationService(CapturingProvider(malformed)).analyze(_bundle())
    assert result.fallback_reason is AIFallbackReason.SCHEMA_VALIDATION_FAILED


def test_unknown_structured_action_field_is_rejected_by_schema() -> None:
    bundle = _bundle()
    evidence_id = bundle.primary_incident_evidence[0].evidence_id
    payload = json.loads(_valid_output(evidence_id))
    payload["close_incident"] = True

    result = AIOrchestrationService(CapturingProvider(json.dumps(payload))).analyze(bundle)

    assert result.fallback_reason is AIFallbackReason.SCHEMA_VALIDATION_FAILED


def test_hallucinated_claim_citation_returns_fallback() -> None:
    bundle = _bundle()
    hallucinated = uuid4()
    payload = json.loads(_valid_output(bundle.primary_incident_evidence[0].evidence_id))
    payload["summary"]["evidence_ids"] = [str(hallucinated)]
    payload["evidence_references"] = [str(hallucinated)]

    result = AIOrchestrationService(CapturingProvider(json.dumps(payload))).analyze(bundle)

    assert result.fallback_reason is AIFallbackReason.CITATION_VALIDATION_FAILED


def test_reference_index_must_equal_actual_claim_citations() -> None:
    bundle = _bundle()
    evidence_id = bundle.primary_incident_evidence[0].evidence_id
    payload = json.loads(_valid_output(evidence_id))
    payload["evidence_references"] = []

    result = AIOrchestrationService(CapturingProvider(json.dumps(payload))).analyze(bundle)

    assert result.fallback_reason is AIFallbackReason.CITATION_VALIDATION_FAILED


@pytest.mark.parametrize(
    "forbidden_text",
    [
        "Change incident status to VERIFIED.",
        "Close the incident now.",
        "Mark the incident VERIFIED.",
        "Change owner to technician B.",
        "Owner should be technician B.",
        "Raise severity to critical.",
        "Severity should be critical.",
        "Change due state to overdue.",
        "Set due time to tomorrow.",
        "Modify the evidence record.",
        "Delete evidence that conflicts with this interpretation.",
        "Edit audit history to remove the earlier action.",
    ],
)
def test_authoritative_action_language_is_rejected(forbidden_text: str) -> None:
    bundle = _bundle()
    evidence_id = bundle.primary_incident_evidence[0].evidence_id

    result = AIOrchestrationService(
        CapturingProvider(_valid_output(evidence_id, summary=forbidden_text))
    ).analyze(bundle)

    assert result.fallback_reason is AIFallbackReason.CLAIM_POLICY_VALIDATION_FAILED


@pytest.fixture
def ai_api_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    from app.core.settings import Settings

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'ai-api.db'}",
        sqlite_wal_enabled=False,
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_id = uuid4()
    incident_id = uuid4()
    evidence_id = uuid4()
    link_id = uuid4()
    occurred = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add(IncidentRecord(id=incident_id, machine_id=machine_id, status=IncidentStatus.OPEN))
        session.flush()
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                component_id=None,
                source_type="MACHINE_EVENT",
                original_source_record_id="ai-api-event",
                original_timestamp=occurred,
                ingestion_timestamp=occurred,
                canonical_event_type="WARNING",
                canonical_payload={"warning": True},
                raw_source_payload={"raw": True},
                provenance={"source_system": "test"},
            )
        )
        session.flush()
        session.add(
            IncidentEvidenceLinkRecord(
                id=link_id,
                incident_id=incident_id,
                evidence_event_id=evidence_id,
                is_active=True,
                relationship_type=IncidentEvidenceRelationshipType.RELATED,
                deterministic_rule_identifier="test.rule",
                link_reason="test",
                linked_at=occurred,
            )
        )

    def override_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    try:
        yield {
            "factory": factory,
            "engine": engine,
            "incident_id": incident_id,
            "evidence_id": evidence_id,
        }
    finally:
        if hasattr(app.state, "llm_provider"):
            delattr(app.state, "llm_provider")
        if hasattr(app.state, "ai_provider"):
            delattr(app.state, "ai_provider")
        app.dependency_overrides.clear()
        engine.dispose()


def _provider_analysis(evidence_id: UUID, *, text: str = "The warning event is recorded.") -> ProviderAIAnalysis:
    return ProviderAIAnalysis(
        status="UNVALIDATED",
        summary="The supplied evidence records a warning event.",
        claims=[
            AIClaim(
                claim_type=AIClaimType.EVENT_OCCURRED,
                text=text,
                evidence_ids=[evidence_id],
            )
        ],
        limitations=[],
    )


class NewCapturingProvider:
    def __init__(self, analysis: ProviderAIAnalysis) -> None:
        self.analysis = analysis
        self.received: list[EvidenceBundleResponse] = []

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        self.received.append(evidence_bundle)
        return AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=self.analysis,
            reason=None,
        )


class NewTimeoutProvider:
    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        del evidence_bundle
        raise TimeoutError("provider timeout")


class NewStaticProvider:
    def __init__(self, status: AIProviderResultStatus, reason: str) -> None:
        self.status = status
        self.reason = reason

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        del evidence_bundle
        return AIProviderResult(status=self.status, analysis=None, reason=self.reason)


def test_ai_api_uses_bundle_and_returns_validated_analysis(ai_api_env: dict[str, Any]) -> None:
    provider = NewCapturingProvider(_provider_analysis(ai_api_env["evidence_id"]))
    app.state.ai_provider = provider

    with TestClient(app) as client:
        response = client.post(f"/api/v1/incidents/{ai_api_env['incident_id']}/ai-analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "VALIDATED_AI"
    assert body["fallback"] is None
    assert body["validated_ai"]["status"] == "VALIDATED"
    assert len(provider.received) == 1
    assert provider.received[0].incident_id == ai_api_env["incident_id"]


def test_non_ai_api_continues_when_llm_fails(ai_api_env: dict[str, Any]) -> None:
    app.state.ai_provider = NewTimeoutProvider()

    with TestClient(app) as client:
        ai_response = client.post(f"/api/v1/incidents/{ai_api_env['incident_id']}/ai-analysis")
        incident_response = client.get(f"/api/v1/incidents/{ai_api_env['incident_id']}")
        health_response = client.get("/health")

    assert ai_response.status_code == 200
    assert ai_response.json()["result_type"] == "FALLBACK"
    assert ai_response.json()["fallback"]["reason"] == "AI_TIMEOUT"
    assert incident_response.status_code == 200
    assert health_response.status_code == 200


def test_non_ai_apis_survive_every_required_ai_failure(ai_api_env: dict[str, Any]) -> None:
    evidence_id = ai_api_env["evidence_id"]
    hallucinated = uuid4()

    scenarios = [
        NewStaticProvider(AIProviderResultStatus.UNAVAILABLE, "provider_offline"),
        NewTimeoutProvider(),
        NewStaticProvider(AIProviderResultStatus.MALFORMED_RESPONSE, "bad_response"),
        NewCapturingProvider(_provider_analysis(hallucinated)),
        NewCapturingProvider(_provider_analysis(evidence_id, text="Close the incident now.")),
    ]

    with TestClient(app) as client:
        for provider in scenarios:
            app.state.ai_provider = provider
            ai_response = client.post(
                f"/api/v1/incidents/{ai_api_env['incident_id']}/ai-analysis"
            )
            assert ai_response.status_code == 200
            assert ai_response.json()["result_type"] == "FALLBACK"

            # Canonical/non-AI read paths remain fully usable after each failure.
            assert client.get(f"/api/v1/incidents/{ai_api_env['incident_id']}").status_code == 200
            assert client.get(
                f"/api/v1/incidents/{ai_api_env['incident_id']}/evidence-bundle"
            ).status_code == 200
            assert client.get("/health").status_code == 200

