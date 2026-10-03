from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Generator
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.capabilities import CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import get_db_session
from tests.sqlite_test_db import create_sqlite_test_engine
from app.main import app
from app.domain.enums import (
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
)
from app.integrations.qdrant import (
    QdrantAvailability,
    QdrantCollectionsResult,
    QdrantConnectivityResult,
)
from app.schemas.ai_provider import (
    AIAnalysis,
    AIClaim,
    AIClaimType,
    AIProviderResult,
    AIProviderResultStatus,
)
from app.schemas.ai_result import AIAnalysisFallbackReason, AIAnalysisResultType
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    SemanticRetrievalMetadata,
)
from app.services.ai_analysis_pipeline import AIAnalysisPipeline
from app.services.ml_ai_capabilities import build_ml_ai_capability_report


class AvailableQdrant:
    def __init__(self, collection: str) -> None:
        self.collection = collection

    def connectivity(self) -> QdrantConnectivityResult:
        return QdrantConnectivityResult(QdrantAvailability.AVAILABLE)

    def discover_collections(self) -> QdrantCollectionsResult:
        return QdrantCollectionsResult(
            QdrantAvailability.AVAILABLE,
            collections=(self.collection,),
        )


class UnavailableQdrant:
    def connectivity(self) -> QdrantConnectivityResult:
        return QdrantConnectivityResult(
            QdrantAvailability.UNAVAILABLE,
            reason="connection_failed",
        )

    def discover_collections(self) -> QdrantCollectionsResult:
        return QdrantCollectionsResult(
            QdrantAvailability.UNAVAILABLE,
            collections=(),
            reason="connection_failed",
        )


class ProbeProvider:
    def __init__(self, available: bool) -> None:
        self.available = available

    def probe_availability(self) -> bool:
        return self.available


class ProhibitedClaimProvider:
    def __init__(self, evidence_id) -> None:
        self.evidence_id = evidence_id

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        del evidence_bundle
        return AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=AIAnalysis(
                status="UNVALIDATED",
                summary="The repair has completely solved the issue.",
                claims=[
                    AIClaim(
                        claim_type=AIClaimType.MAINTENANCE_RECORDED,
                        text="The repair has completely solved the issue.",
                        evidence_ids=[self.evidence_id],
                    )
                ],
                limitations=[],
            ),
        )


@pytest.fixture
def mode_client(tmp_path) -> Generator[TestClient, None, None]:
    test_settings = Settings(
        environment="test",
    )
    engine = create_sqlite_test_engine(tmp_path / 'modes.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )

    def override_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def enabled_settings(**overrides) -> Settings:
    values = dict(
        environment="test",
        semantic_search_enabled=True,
        qdrant_url="https://qdrant.example.test",
        qdrant_collection="mine_trace_evidence",
        embedding_provider="qdrant_cloud_inference",
        embedding_model="sentence-transformers/all-minilm-l6-v2",
        ai_enabled=True,
        ai_provider="openai",
        ai_model="test-model",
        ai_api_key="placeholder-only",
    )
    values.update(overrides)
    return Settings(**values)


def bundle() -> tuple[EvidenceBundleResponse, object]:
    evidence_id = uuid4()
    machine_id = uuid4()
    now = datetime(2026, 10, 3, 10, 30, tzinfo=timezone.utc)
    item = BundleEvidenceItem(
        evidence_id=evidence_id,
        machine_id=machine_id,
        component_id=None,
        source_type="HUMAN_OBSERVATION",
        original_source_record_id="obs-1",
        original_timestamp=now,
        ingestion_timestamp=now,
        canonical_event_type="OBSERVATION",
        canonical_payload={"note": "Grinding sound"},
        raw_source_payload={"note": "Grinding sound"},
        provenance={"source_system": "operator-log"},
        source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
        inclusion_reason="active incident evidence",
        relationship_type=IncidentEvidenceRelationshipType.RELATED,
        deterministic_rule_identifier="test.rule",
    )
    response = EvidenceBundleResponse(
        incident_id=uuid4(),
        status=EvidenceBundleStatus.READY,
        primary_incident_evidence=[item],
        selected_exact_history=[],
        selected_semantic_history=[],
        verification_context=[],
        evidence_time_context_snapshots=[],
        provenance_index=[],
        completeness=EvidenceBundleCompleteness(
            canonical_readiness_policy="test",
            status_reason="ready",
            semantic_retrieval=SemanticRetrievalMetadata(
                configured=True,
                attempted=True,
                failed=False,
            ),
        ),
    )
    return response, evidence_id


def assert_canonical_reads_operational(mode_client) -> None:
    assert mode_client.get("/health").status_code == 200
    assert mode_client.get("/api/v1/machines").status_code == 200
    assert mode_client.get("/api/v1/incidents").status_code == 200


def test_mode_a_qdrant_embeddings_and_ai_available(mode_client) -> None:
    observer = MLAIObservability()
    settings = enabled_settings()
    state = SimpleNamespace(
        qdrant_service=AvailableQdrant(settings.qdrant_collection),
        embedding_provider=ProbeProvider(True),
        ai_provider=ProbeProvider(True),
    )

    report = build_ml_ai_capability_report(
        app_state=state,
        settings=settings,
        observability=observer,
    )

    assert report.qdrant_semantic.status is CapabilityStatus.AVAILABLE
    assert report.embedding_provider.status is CapabilityStatus.AVAILABLE
    assert report.ai_provider.status is CapabilityStatus.AVAILABLE
    assert_canonical_reads_operational(mode_client)


def test_mode_b_qdrant_semantic_unavailable_core_still_operates(mode_client) -> None:
    observer = MLAIObservability()
    settings = enabled_settings()
    state = SimpleNamespace(
        qdrant_service=UnavailableQdrant(),
        embedding_provider=ProbeProvider(True),
        ai_provider=ProbeProvider(True),
    )

    report = build_ml_ai_capability_report(
        app_state=state,
        settings=settings,
        observability=observer,
    )

    assert report.qdrant_semantic.status is CapabilityStatus.UNAVAILABLE
    assert report.embedding_provider.status is CapabilityStatus.AVAILABLE
    assert report.ai_provider.status is CapabilityStatus.AVAILABLE
    assert_canonical_reads_operational(mode_client)


def test_mode_c_ai_unavailable_core_still_operates(mode_client) -> None:
    observer = MLAIObservability()
    settings = enabled_settings()
    state = SimpleNamespace(
        qdrant_service=AvailableQdrant(settings.qdrant_collection),
        embedding_provider=ProbeProvider(True),
        ai_provider=ProbeProvider(False),
    )

    report = build_ml_ai_capability_report(
        app_state=state,
        settings=settings,
        observability=observer,
    )

    assert report.qdrant_semantic.status is CapabilityStatus.AVAILABLE
    assert report.embedding_provider.status is CapabilityStatus.AVAILABLE
    assert report.ai_provider.status is CapabilityStatus.UNAVAILABLE
    assert_canonical_reads_operational(mode_client)


def test_mode_d_ai_response_rejected_falls_back_and_core_still_operates(mode_client) -> None:
    evidence_bundle, evidence_id = bundle()
    observer = MLAIObservability()

    result = AIAnalysisPipeline(
        ProhibitedClaimProvider(evidence_id),
        observability=observer,
    ).analyze(evidence_bundle)

    assert result.result_type is AIAnalysisResultType.FALLBACK
    assert result.fallback is not None
    assert result.fallback.reason is AIAnalysisFallbackReason.PROHIBITED_CLAIM
    signals = observer.snapshot()
    assert signals.ai_claim_policy_rejections == 1
    assert signals.fallback_reasons["PROHIBITED_CLAIM"] == 1
    assert_canonical_reads_operational(mode_client)


def test_disabled_capabilities_are_reported_as_disabled_not_available(mode_client) -> None:
    observer = MLAIObservability()
    settings = Settings(environment="test", semantic_search_enabled=False, ai_enabled=False)
    report = build_ml_ai_capability_report(
        app_state=SimpleNamespace(), settings=settings, observability=observer
    )

    assert report.qdrant_semantic.status is CapabilityStatus.DISABLED
    assert report.embedding_provider.status is CapabilityStatus.DISABLED
    assert report.ai_provider.status is CapabilityStatus.DISABLED

    response = mode_client.get("/api/v1/health/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["qdrant_semantic"]["status"] == "DISABLED"
    assert payload["embedding_provider"]["status"] == "DISABLED"
    assert payload["ai_provider"]["status"] == "DISABLED"
