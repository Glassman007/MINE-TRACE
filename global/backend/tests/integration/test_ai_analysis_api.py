from __future__ import annotations

from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import get_db_session
from tests.sqlite_test_db import create_sqlite_test_engine
from app.domain.enums import (
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    VerificationRuleType,
)
from app.integrations.embeddings.base import EmbeddingKind, EmbeddingVector
from app.integrations.qdrant import QdrantService
from app.main import app
from app.models import (
    ComponentRecord,
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationEvidenceRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.ai_provider import (
    AIAnalysis,
    AIClaim,
    AIClaimType,
    AIProviderResult,
    AIProviderResultStatus,
)
from app.schemas.evidence_bundle import EvidenceBundleResponse
from app.services.semantic_history import SemanticHistoryService


class FixedEmbeddingProvider:
    def embed_query(self, text: str) -> EmbeddingVector:
        assert text.strip()
        return EmbeddingVector.validated(
            [0.2, 0.4, 0.6],
            provider="test",
            model="test-query-model",
            kind=EmbeddingKind.QUERY,
        )

    def embed_document(self, text: str) -> EmbeddingVector:  # pragma: no cover - not used by retrieval
        raise AssertionError("document embedding must not run during retrieval")

    def embed_documents(self, texts: Sequence[str]):  # pragma: no cover - not used by retrieval
        raise AssertionError("batch document embedding must not run during retrieval")


class FakeQdrantModels:
    class MatchValue:
        def __init__(self, *, value: str) -> None:
            self.value = value

    class FieldCondition:
        def __init__(self, *, key: str, match: object) -> None:
            self.key = key
            self.match = match

    class Filter:
        def __init__(self, *, must: list[object]) -> None:
            self.must = must


class FakeQdrantClient:
    def __init__(self, candidate_id: UUID) -> None:
        self.candidate_id = candidate_id
        self.queries: list[dict[str, Any]] = []

    def query_points(self, **kwargs: Any):
        self.queries.append(kwargs)
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id=str(self.candidate_id),
                    payload={"evidence_id": str(self.candidate_id)},
                    score=0.82,
                )
            ]
        )


class CapturingAIProvider:
    def __init__(self, evidence_id: UUID) -> None:
        self.evidence_id = evidence_id
        self.received: list[EvidenceBundleResponse] = []

    @property
    def call_count(self) -> int:
        return len(self.received)

    def analyze(self, evidence_bundle: EvidenceBundleResponse) -> AIProviderResult:
        self.received.append(evidence_bundle)
        return AIProviderResult(
            status=AIProviderResultStatus.UNVALIDATED,
            analysis=AIAnalysis(
                status="UNVALIDATED",
                summary="The supplied bundle records the warning event.",
                claims=[
                    AIClaim(
                        claim_type=AIClaimType.EVENT_OCCURRED,
                        text="The warning event is present in canonical evidence.",
                        evidence_ids=[self.evidence_id],
                    )
                ],
                limitations=["Semantic similarity is contextual only."],
            ),
            reason=None,
        )


@pytest.fixture
def ai_action_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    settings = Settings(
        environment="test",
        semantic_search_enabled=True,
        qdrant_url="https://qdrant.example.test",
        qdrant_collection="mine_trace_evidence",
        embedding_provider="qdrant_cloud_inference",
        embedding_model="sentence-transformers/all-minilm-l6-v2",
        semantic_top_k=5,
        ai_enabled=True,
        ai_provider="openai",
        ai_model="test-model",
        ai_api_key="test-placeholder-key",
    )
    engine = create_sqlite_test_engine(tmp_path / 'ai-action.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    machine_id = uuid4()
    component_id = uuid4()
    incident_id = uuid4()
    exact_id = uuid4()
    semantic_id = uuid4()
    primary_id = uuid4()
    verification_rule_id = uuid4()
    verification_run_id = uuid4()
    now = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)

    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id, display_name="EX-01"))
        session.flush()
        session.add(ComponentRecord(id=component_id, machine_id=machine_id, display_name="Hydraulics"))
        session.flush()
        session.add(
            IncidentRecord(
                id=incident_id,
                machine_id=machine_id,
                status=IncidentStatus.OPEN,
                owner_ref="shift-a",
                severity="HIGH",
                due_state="DUE",
            )
        )
        session.flush()

        records = [
            EvidenceEventRecord(
                id=exact_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=component_id,
                source_type="HUMAN_OBSERVATION",
                original_source_record_id="exact-history",
                original_timestamp=now - timedelta(days=2),
                ingestion_timestamp=now - timedelta(days=2),
                canonical_event_type="HYDRAULIC_WARNING",
                canonical_payload={"note": "Earlier hydraulic pressure warning."},
                raw_source_payload={"note": "Earlier hydraulic pressure warning."},
                provenance={"source_system": "operator-log"},
            ),
            EvidenceEventRecord(
                id=semantic_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=component_id,
                source_type="MAINTENANCE_RECORD",
                original_source_record_id="semantic-history",
                original_timestamp=now - timedelta(days=4),
                ingestion_timestamp=now - timedelta(days=4),
                canonical_event_type="MAINTENANCE_NOTE",
                canonical_payload={"description": "Hydraulic circuit inspection after pressure noise."},
                raw_source_payload={"description": "Hydraulic circuit inspection after pressure noise."},
                provenance={"source_system": "maintenance-log"},
            ),
            EvidenceEventRecord(
                id=primary_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=component_id,
                source_type="HUMAN_OBSERVATION",
                original_source_record_id="primary-warning",
                original_timestamp=now,
                ingestion_timestamp=now,
                canonical_event_type="HYDRAULIC_WARNING",
                canonical_payload={"note": "Hydraulic pressure warning and audible whine."},
                raw_source_payload={"note": "Hydraulic pressure warning and audible whine."},
                provenance={"source_system": "operator-log"},
            ),
        ]
        session.add_all(records)
        session.flush()
        session.add(
            IncidentEvidenceLinkRecord(
                id=uuid4(),
                incident_id=incident_id,
                evidence_event_id=primary_id,
                is_active=True,
                relationship_type=IncidentEvidenceRelationshipType.RELATED,
                deterministic_rule_identifier="test.rule",
                link_reason="primary incident evidence",
                linked_at=now,
            )
        )
        session.add(
            VerificationRuleRecord(
                id=verification_rule_id,
                identifier="test.no-event",
                name="Test no-event verification",
                rule_type=VerificationRuleType.NO_EVENT,
                window_minutes=30,
            )
        )
        session.flush()
        session.add(
            VerificationRunRecord(
                id=verification_run_id,
                incident_id=incident_id,
                source_machine_id=machine_id,
                verification_rule_id=verification_rule_id,
                result=None,
                started_at=now,
                window_ends_at=now + timedelta(minutes=30),
                completed_at=None,
            )
        )
        session.flush()
        session.add(
            VerificationEvidenceRecord(
                id=uuid4(),
                verification_run_id=verification_run_id,
                evidence_event_id=primary_id,
            )
        )

    def override_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    qdrant_client = FakeQdrantClient(semantic_id)
    qdrant = QdrantService(
        collection_name=settings.qdrant_collection,
        distance=settings.qdrant_distance,
        client=qdrant_client,
        models_module=FakeQdrantModels,
    )
    semantic_service = SemanticHistoryService(
        lambda: SQLAlchemyUnitOfWork(factory),
        FixedEmbeddingProvider(),
        qdrant,
        settings,
    )
    provider = CapturingAIProvider(primary_id)

    old_semantic = getattr(app.state, "semantic_history_service", None)
    old_provider = getattr(app.state, "ai_provider", None)
    app.state.semantic_history_service = semantic_service
    app.state.ai_provider = provider
    app.dependency_overrides[get_db_session] = override_session
    try:
        yield {
            "factory": factory,
            "engine": engine,
            "machine_id": machine_id,
            "component_id": component_id,
            "incident_id": incident_id,
            "primary_id": primary_id,
            "exact_id": exact_id,
            "semantic_id": semantic_id,
            "provider": provider,
            "qdrant_client": qdrant_client,
        }
    finally:
        app.dependency_overrides.clear()
        if old_semantic is None:
            if hasattr(app.state, "semantic_history_service"):
                delattr(app.state, "semantic_history_service")
        else:
            app.state.semantic_history_service = old_semantic
        if old_provider is None:
            if hasattr(app.state, "ai_provider"):
                delattr(app.state, "ai_provider")
        else:
            app.state.ai_provider = old_provider
        engine.dispose()


def _canonical_snapshot(factory: sessionmaker[Session], incident_id: UUID) -> tuple[Any, ...]:
    with factory() as session:
        incident = session.get(IncidentRecord, incident_id)
        assert incident is not None
        evidence = session.scalars(
            select(EvidenceEventRecord).order_by(EvidenceEventRecord.id)
        ).all()
        links = session.scalars(
            select(IncidentEvidenceLinkRecord).order_by(IncidentEvidenceLinkRecord.id)
        ).all()
        verification = session.scalars(
            select(VerificationRunRecord).order_by(VerificationRunRecord.id)
        ).all()
        verification_evidence = session.scalars(
            select(VerificationEvidenceRecord).order_by(VerificationEvidenceRecord.id)
        ).all()
        audits = session.scalars(
            select(IncidentAuditEventRecord).order_by(IncidentAuditEventRecord.id)
        ).all()
        return (
            (incident.status, incident.owner_ref, incident.severity, incident.due_state, incident.due_time),
            tuple(
                (
                    row.id,
                    row.machine_id,
                    row.component_id,
                    row.source_type,
                    row.original_timestamp,
                    row.canonical_event_type,
                    row.canonical_payload.copy(),
                    row.provenance.copy(),
                )
                for row in evidence
            ),
            tuple(
                (row.id, row.incident_id, row.evidence_event_id, row.is_active, row.relationship_type, row.unlinked_at)
                for row in links
            ),
            tuple((row.id, row.result, row.started_at, row.window_ends_at, row.completed_at) for row in verification),
            tuple((row.id, row.verification_run_id, row.evidence_event_id) for row in verification_evidence),
            tuple((row.id, row.action, row.occurred_at, row.payload.copy()) for row in audits),
        )


def test_explicit_ai_post_runs_full_read_only_pipeline(ai_action_env: dict[str, Any]) -> None:
    before = _canonical_snapshot(ai_action_env["factory"], ai_action_env["incident_id"])

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/incidents/{ai_action_env['incident_id']}/ai-analysis"
        )

    after = _canonical_snapshot(ai_action_env["factory"], ai_action_env["incident_id"])

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "VALIDATED_AI"
    assert body["validated_ai"]["status"] == "VALIDATED"
    assert body["fallback"] is None

    provider = ai_action_env["provider"]
    assert provider.call_count == 1
    bundle = provider.received[0]
    assert bundle.incident_id == ai_action_env["incident_id"]
    assert [item.evidence_id for item in bundle.primary_incident_evidence] == [
        ai_action_env["primary_id"]
    ]
    assert ai_action_env["exact_id"] in {
        item.evidence_id for item in bundle.selected_exact_history
    }
    assert ai_action_env["semantic_id"] in {
        item.evidence_id for item in bundle.selected_semantic_history
    }
    semantic_item = next(
        item
        for item in bundle.selected_semantic_history
        if item.evidence_id == ai_action_env["semantic_id"]
    )
    assert semantic_item.canonical_payload == {
        "description": "Hydraulic circuit inspection after pressure noise."
    }
    assert semantic_item.provenance == {"source_system": "maintenance-log"}
    assert semantic_item.similarity_score == pytest.approx(0.82)

    qdrant_queries = ai_action_env["qdrant_client"].queries
    assert len(qdrant_queries) == 1
    assert qdrant_queries[0]["limit"] == 5
    # A Qdrant query is enrichment only; the complete canonical snapshot remains identical.
    assert before == after


def test_get_endpoints_never_invoke_ai_provider(ai_action_env: dict[str, Any]) -> None:
    provider = ai_action_env["provider"]
    assert provider.call_count == 0

    with TestClient(app) as client:
        responses = [
            client.get(f"/api/v1/incidents/{ai_action_env['incident_id']}"),
            client.get(f"/api/v1/incidents/{ai_action_env['incident_id']}/evidence"),
            client.get(f"/api/v1/machines/{ai_action_env['machine_id']}/sessions"),
            client.get(f"/api/v1/incidents/{ai_action_env['incident_id']}/evidence-bundle"),
            client.get("/api/v1/health"),
        ]
        wrong_method = client.get(
            f"/api/v1/incidents/{ai_action_env['incident_id']}/ai-analysis"
        )

    assert all(response.status_code == 200 for response in responses)
    assert wrong_method.status_code == 405
    assert provider.call_count == 0


def test_unknown_incident_never_invokes_provider(ai_action_env: dict[str, Any]) -> None:
    with TestClient(app) as client:
        response = client.post(f"/api/v1/incidents/{uuid4()}/ai-analysis")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INCIDENT_NOT_FOUND"
    assert ai_action_env["provider"].call_count == 0
