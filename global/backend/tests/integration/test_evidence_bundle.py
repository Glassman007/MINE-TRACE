from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.domain.enums import (
    ContextQuality,
    EvidenceBundleSection,
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    VerificationRuleType,
)
from app.models import (
    ComponentRecord,
    ContextSnapshotRecord,
    EvidenceEventRecord,
    IncidentEvidenceLinkRecord,
    IncidentRecord,
    MachineRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_history import (
    SemanticHistoryEvidence,
    SemanticHistoryFailure,
    SemanticHistoryResponse,
)
from app.services.evidence_bundle import EvidenceBundleService


class FakeSemanticHistory:
    def __init__(self, responses: dict[UUID, SemanticHistoryResponse] | None = None):
        self.responses = responses or {}
        self.calls: list[UUID] = []

    def search_similar_history(self, evidence_id: UUID) -> SemanticHistoryResponse:
        self.calls.append(evidence_id)
        return self.responses.get(
            evidence_id,
            SemanticHistoryResponse(available=True, results=[]),
        )


@pytest.fixture
def bundle_env(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    settings = Settings(
        environment="test",
        history_lookback_days=30,
        evidence_bundle_limit=100,
    )
    engine = create_sqlite_test_engine(tmp_path / 'bundle.db')
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
    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id))
        session.flush()
        session.add(ComponentRecord(id=component_id, machine_id=machine_id))
        session.flush()
        session.add(
            IncidentRecord(
                id=incident_id,
                machine_id=machine_id,
                status=IncidentStatus.OPEN,
            )
        )

    try:
        yield {
            "settings": settings,
            "factory": factory,
            "machine_id": machine_id,
            "component_id": component_id,
            "incident_id": incident_id,
        }
    finally:
        engine.dispose()


def _add_evidence(
    env: dict[str, Any],
    *,
    record_id: str,
    occurred_at: datetime,
    event_type: str = "HYDRAULIC_WARNING",
    component_id: UUID | None = None,
    provenance: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> UUID:
    evidence_id = uuid4()
    with env["factory"].begin() as session:
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=env["machine_id"],
                source_machine_id=env["machine_id"],
                component_id=component_id if component_id is not None else env["component_id"],
                source_type="TEST",
                original_source_record_id=record_id,
                original_timestamp=occurred_at,
                ingestion_timestamp=occurred_at + timedelta(minutes=7),
                canonical_event_type=event_type,
                canonical_payload=payload or {"record": record_id},
                raw_source_payload={"raw": record_id},
                provenance=provenance or {"source_system": "test", "record": record_id},
            )
        )
    return evidence_id


def _link_primary(env: dict[str, Any], evidence_id: UUID, *, linked_at: datetime) -> UUID:
    link_id = uuid4()
    with env["factory"].begin() as session:
        session.add(
            IncidentEvidenceLinkRecord(
                id=link_id,
                incident_id=env["incident_id"],
                evidence_event_id=evidence_id,
                is_active=True,
                relationship_type=IncidentEvidenceRelationshipType.RELATED,
                deterministic_rule_identifier="test.rule",
                link_reason="test primary association",
                linked_at=linked_at,
            )
        )
    return link_id


def _semantic_result(env: dict[str, Any], evidence_id: UUID, *, score: float):
    with env["factory"]() as session:
        evidence = session.get(EvidenceEventRecord, evidence_id)
        assert evidence is not None
        return SemanticHistoryEvidence(
            evidence_id=evidence.id,
            machine_id=evidence.machine_id,
            component_id=evidence.component_id,
            evidence_type=evidence.source_type,
            original_timestamp=evidence.original_timestamp.replace(tzinfo=timezone.utc)
            if evidence.original_timestamp.tzinfo is None
            else evidence.original_timestamp,
            canonical_event_type=evidence.canonical_event_type,
            canonical_payload=evidence.canonical_payload,
            provenance=evidence.provenance,
            similarity_score=score,
        )


def _service(env: dict[str, Any], semantic=None) -> EvidenceBundleService:
    return EvidenceBundleService(
        lambda: SQLAlchemyUnitOfWork(env["factory"]),
        env["settings"],
        semantic_history=semantic,
    )


def test_canonical_evidence_only_is_ready(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    primary = _add_evidence(bundle_env, record_id="primary", occurred_at=t0)
    _link_primary(bundle_env, primary, linked_at=t0)

    bundle = _service(bundle_env).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.READY
    assert [item.evidence_id for item in bundle.primary_incident_evidence] == [primary]
    assert bundle.selected_exact_history == []
    assert bundle.selected_semantic_history == []
    assert bundle.completeness.semantic_retrieval.configured is False
    assert bundle.completeness.incomplete_sections == []


def test_canonical_plus_exact_history(bundle_env: dict[str, Any]) -> None:
    primary_time = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    exact = _add_evidence(
        bundle_env,
        record_id="exact",
        occurred_at=primary_time - timedelta(days=2),
    )
    primary = _add_evidence(bundle_env, record_id="primary", occurred_at=primary_time)
    _link_primary(bundle_env, primary, linked_at=primary_time)

    bundle = _service(bundle_env).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.READY
    assert [item.evidence_id for item in bundle.selected_exact_history] == [exact]
    assert bundle.selected_exact_history[0].source_classification is EvidenceBundleSourceClassification.EXACT_HISTORY
    assert bundle.selected_exact_history[0].anchor_evidence_id == primary


def test_canonical_plus_semantic_history(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    primary = _add_evidence(bundle_env, record_id="primary", occurred_at=t0)
    semantic_id = _add_evidence(
        bundle_env,
        record_id="semantic",
        occurred_at=t0 - timedelta(days=1),
        event_type="VIBRATION_NOTE",
        payload={"authoritative": "sqlite"},
    )
    _link_primary(bundle_env, primary, linked_at=t0)
    semantic_hit = _semantic_result(bundle_env, semantic_id, score=0.93)
    semantic_hit.canonical_payload = {"derived_index_payload": "must-not-win"}
    semantic = FakeSemanticHistory(
        {
            primary: SemanticHistoryResponse(
                available=True,
                results=[semantic_hit],
            )
        }
    )

    bundle = _service(bundle_env, semantic).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.READY
    assert [item.evidence_id for item in bundle.selected_semantic_history] == [semantic_id]
    assert bundle.selected_semantic_history[0].canonical_payload == {"authoritative": "sqlite"}
    assert bundle.selected_semantic_history[0].source_classification is EvidenceBundleSourceClassification.SEMANTIC_HISTORY


def test_global_dedup_prefers_exact_over_semantic(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    duplicate = _add_evidence(
        bundle_env,
        record_id="duplicate",
        occurred_at=t0 - timedelta(hours=2),
    )
    primary = _add_evidence(bundle_env, record_id="primary", occurred_at=t0)
    _link_primary(bundle_env, primary, linked_at=t0)
    semantic = FakeSemanticHistory(
        {
            primary: SemanticHistoryResponse(
                available=True,
                results=[_semantic_result(bundle_env, duplicate, score=0.99)],
            )
        }
    )

    bundle = _service(bundle_env, semantic).build(bundle_env["incident_id"])

    assert [item.evidence_id for item in bundle.selected_exact_history] == [duplicate]
    assert bundle.selected_semantic_history == []
    all_ids = [
        *(item.evidence_id for item in bundle.primary_incident_evidence),
        *(item.evidence_id for item in bundle.selected_exact_history),
        *(item.evidence_id for item in bundle.selected_semantic_history),
    ]
    assert len(all_ids) == len(set(all_ids))


def test_qdrant_outage_makes_usable_bundle_partial(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    primary = _add_evidence(bundle_env, record_id="primary", occurred_at=t0)
    _link_primary(bundle_env, primary, linked_at=t0)
    semantic = FakeSemanticHistory(
        {
            primary: SemanticHistoryResponse(
                available=False,
                failure=SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE,
            )
        }
    )

    bundle = _service(bundle_env, semantic).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.PARTIAL
    assert bundle.primary_incident_evidence[0].evidence_id == primary
    assert bundle.completeness.semantic_retrieval.failed is True
    assert bundle.completeness.semantic_retrieval.failures == [
        SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE
    ]
    assert EvidenceBundleSection.SELECTED_SEMANTIC_HISTORY in bundle.completeness.incomplete_sections


def test_semantic_outage_does_not_remove_exact_history(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    exact = _add_evidence(
        bundle_env,
        record_id="exact-before-qdrant-outage",
        occurred_at=t0 - timedelta(hours=1),
    )
    primary = _add_evidence(bundle_env, record_id="primary-qdrant-outage", occurred_at=t0)
    _link_primary(bundle_env, primary, linked_at=t0)
    semantic = FakeSemanticHistory(
        {
            primary: SemanticHistoryResponse(
                available=False,
                failure=SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE,
            )
        }
    )

    bundle = _service(bundle_env, semantic).build(bundle_env["incident_id"])

    assert [item.evidence_id for item in bundle.selected_exact_history] == [exact]
    assert bundle.selected_semantic_history == []
    assert bundle.status is EvidenceBundleStatus.PARTIAL


def test_insufficient_when_no_canonical_primary_evidence(bundle_env: dict[str, Any]) -> None:
    bundle = _service(bundle_env).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.INSUFFICIENT_EVIDENCE
    assert bundle.primary_incident_evidence == []
    assert EvidenceBundleSection.PRIMARY_INCIDENT_EVIDENCE in bundle.completeness.incomplete_sections


def test_semantic_only_cannot_upgrade_insufficient_bundle(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    semantic_id = _add_evidence(
        bundle_env,
        record_id="semantic-only",
        occurred_at=t0 - timedelta(days=1),
        event_type="OTHER_EVENT",
    )
    # There is deliberately no active primary association to anchor canonical
    # incident evidence. Even a configured semantic provider cannot establish it.
    semantic = FakeSemanticHistory()
    semantic.responses[semantic_id] = SemanticHistoryResponse(
        available=True,
        results=[_semantic_result(bundle_env, semantic_id, score=0.99)],
    )

    bundle = _service(bundle_env, semantic).build(bundle_env["incident_id"])

    assert bundle.status is EvidenceBundleStatus.INSUFFICIENT_EVIDENCE
    assert bundle.selected_semantic_history == []
    assert semantic.calls == []


def test_bundle_ordering_is_deterministic(bundle_env: dict[str, Any]) -> None:
    base = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    primary_late = _add_evidence(bundle_env, record_id="p-late", occurred_at=base)
    primary_early = _add_evidence(
        bundle_env, record_id="p-early", occurred_at=base - timedelta(minutes=10)
    )
    _link_primary(bundle_env, primary_late, linked_at=base - timedelta(hours=2))
    _link_primary(bundle_env, primary_early, linked_at=base + timedelta(hours=2))

    exact_old = _add_evidence(
        bundle_env, record_id="e-old", occurred_at=base - timedelta(days=3)
    )
    exact_new = _add_evidence(
        bundle_env, record_id="e-new", occurred_at=base - timedelta(days=1)
    )
    semantic_low = _add_evidence(
        bundle_env,
        record_id="s-low",
        occurred_at=base - timedelta(hours=5),
        event_type="SEM_LOW",
    )
    semantic_high = _add_evidence(
        bundle_env,
        record_id="s-high",
        occurred_at=base - timedelta(hours=7),
        event_type="SEM_HIGH",
    )
    semantic = FakeSemanticHistory(
        {
            primary_early: SemanticHistoryResponse(
                available=True,
                results=[
                    _semantic_result(bundle_env, semantic_low, score=0.80),
                    _semantic_result(bundle_env, semantic_high, score=0.95),
                ],
            ),
            primary_late: SemanticHistoryResponse(available=True, results=[]),
        }
    )

    service = _service(bundle_env, semantic)
    first = service.build(bundle_env["incident_id"])
    second = service.build(bundle_env["incident_id"])

    assert [x.evidence_id for x in first.primary_incident_evidence] == [
        primary_early,
        primary_late,
    ]
    assert [x.evidence_id for x in first.selected_exact_history] == [exact_old, exact_new]
    assert [x.evidence_id for x in first.selected_semantic_history] == [
        semantic_high,
        semantic_low,
    ]
    assert first.model_dump() == second.model_dump()


def test_bundle_includes_verification_context_snapshots_and_provenance(bundle_env: dict[str, Any]) -> None:
    t0 = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    primary = _add_evidence(
        bundle_env,
        record_id="rich-primary",
        occurred_at=t0,
        provenance={"source_system": "ecu", "record": "rich-primary"},
    )
    _link_primary(bundle_env, primary, linked_at=t0)

    rule_id = uuid4()
    run_id = uuid4()
    with bundle_env["factory"].begin() as session:
        session.add(
            ContextSnapshotRecord(
                id=uuid4(),
                evidence_event_id=primary,
                quality=None,
                snapshot_payload={
                    "shift": {"value": "A", "quality": ContextQuality.KNOWN, "freshness_basis": "event"},
                    "location": {"value": "L4", "quality": ContextQuality.KNOWN, "freshness_basis": "event"},
                    "machine_operating_state": {"value": "RUNNING", "quality": ContextQuality.KNOWN, "freshness_basis": "event"},
                    "workload": {"value": 0.7, "quality": ContextQuality.KNOWN, "freshness_basis": "event"},
                    "environment": {"value": None, "quality": ContextQuality.UNKNOWN, "freshness_basis": "not-reported"},
                },
            )
        )
        session.add(
            VerificationRuleRecord(
                id=rule_id,
                identifier="bundle.no-event",
                name="Bundle test rule",
                rule_type=VerificationRuleType.NO_EVENT,
                window_minutes=30,
            )
        )
        session.flush()
        session.add(
            VerificationRunRecord(
                id=run_id,
                incident_id=bundle_env["incident_id"],
                source_machine_id=bundle_env["machine_id"],
                verification_rule_id=rule_id,
                started_at=t0,
                window_ends_at=t0 + timedelta(minutes=30),
                completed_at=None,
                result=None,
            )
        )

    bundle = _service(bundle_env).build(bundle_env["incident_id"])

    assert bundle.verification_context[0].verification_run_id == run_id
    assert bundle.evidence_time_context_snapshots[0].evidence_id == primary
    assert bundle.evidence_time_context_snapshots[0].context_snapshots[0].context.shift.value == "A"
    assert bundle.provenance_index[0].evidence_id == primary
    assert bundle.provenance_index[0].provenance["source_system"] == "ecu"


def test_evidence_bundle_api_route_is_registered() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/incidents/{incident_id}/evidence-bundle" in paths


def test_evidence_bundle_endpoint_returns_bundle(bundle_env: dict[str, Any]) -> None:
    from collections.abc import Generator

    from fastapi.testclient import TestClient

    from app.db.session import get_db_session
    from app.main import app

    t0 = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    primary = _add_evidence(bundle_env, record_id="api-primary", occurred_at=t0)
    _link_primary(bundle_env, primary, linked_at=t0)

    def override_session() -> Generator[Session, None, None]:
        session = bundle_env["factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    if hasattr(app.state, "semantic_history_service"):
        delattr(app.state, "semantic_history_service")
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/incidents/{bundle_env['incident_id']}/evidence-bundle"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["primary_incident_evidence"][0]["evidence_id"] == str(primary)
