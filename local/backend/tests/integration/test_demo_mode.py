from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.session import create_database_engine
from app.demo.embedding import DemoHashEmbeddingProvider
from app.demo.fixtures import COMPONENT_IDS, DEMO_MACHINE_ID
from app.demo.seed import DemoSeedError, seed_demo
from app.domain.enums import IncidentStatus, OperatingSessionState, SyncOutboxState, VerificationRunResult
from app.integrations.qdrant.types import QdrantAvailability, QdrantCollectionResult, QdrantDistance, QdrantMutationResult, QdrantSearchResult
from app.integrations.semantic import SemanticIndexHit
from app.models import ComponentRecord, EvidenceEventRecord, IncidentRecord, MachineRecord, MachineSessionReportRecord, OperatingSessionRecord, SyncConflictRecord, SyncOutboxItemRecord, VerificationRunRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_search import SemanticSearchRequest
from app.services.return_to_service import ReturnToServiceService
from app.services.semantic_indexing import CanonicalEvidenceIndexingService, SemanticRebuildState
from app.services.semantic_search import NaturalLanguageSemanticSearchService


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        environment="test",
        demo_mode=True,
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        sqlite_wal_enabled=False,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _db(settings: Settings):
    engine = create_database_engine(settings)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    return engine, factory, lambda: SQLAlchemyUnitOfWork(factory)


def test_demo_mode_seeds_complete_real_workflow_and_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = seed_demo(settings, reset=True)
    second = seed_demo(settings)

    assert second == first
    assert first.machine_id == str(DEMO_MACHINE_ID)
    assert first.component_count == 7
    assert first.sync_state == SyncOutboxState.CONFLICT.value
    assert first.return_to_service_state == "DO_NOT_RETURN"

    engine, factory, uow_factory = _db(settings)
    try:
        with factory() as session:
            machine = session.get(MachineRecord, DEMO_MACHINE_ID)
            assert machine is not None
            assert machine.asset_code == "EXC-204"
            assert machine.machine_type == "Hydraulic Excavator"
            assert machine.site_name == "North Ridge Mine"
            assert session.scalar(select(func.count(ComponentRecord.id))) == 7

            primary = session.scalar(select(EvidenceEventRecord).where(
                EvidenceEventRecord.original_source_record_id == "DEMO-EXC204-HYD-OBS-001"
            ))
            assert primary is not None
            primary_incident = session.get(IncidentRecord, __import__('uuid').UUID(first.primary_incident_id))
            unresolved = session.get(IncidentRecord, __import__('uuid').UUID(first.unresolved_incident_id))
            assert primary_incident is not None and primary_incident.status is IncidentStatus.VERIFIED
            assert unresolved is not None and unresolved.status is IncidentStatus.OPEN

            runs = session.scalars(select(VerificationRunRecord).where(
                VerificationRunRecord.incident_id == primary_incident.id
            )).all()
            assert len(runs) == 1
            assert runs[0].result is VerificationRunResult.SUCCEEDED

            closed = session.get(OperatingSessionRecord, __import__('uuid').UUID(first.closed_session_id))
            active = session.get(OperatingSessionRecord, __import__('uuid').UUID(first.active_session_id))
            assert closed is not None and closed.state is OperatingSessionState.CLOSED
            assert closed.operating_hours == 5.0
            assert active is not None and active.state is OperatingSessionState.OPEN

            report = session.get(MachineSessionReportRecord, __import__('uuid').UUID(first.report_id))
            assert report is not None
            assert report.payload["evidence_manifest"]["entries"]
            assert report.payload["maintenance_actions"]
            assert report.payload["verification_results"]

            outbox = session.scalar(select(SyncOutboxItemRecord).where(
                SyncOutboxItemRecord.package_id == __import__('uuid').UUID(first.sync_package_id)
            ))
            assert outbox is not None and outbox.state is SyncOutboxState.CONFLICT
            assert outbox.transport_available is True
            assert session.scalar(select(func.count(SyncConflictRecord.conflict_id))) == 1

        rts = ReturnToServiceService(settings, uow_factory).evaluate()
        assert rts.state.value == "DO_NOT_RETURN"
        assert any(reason.incident_id == __import__('uuid').UUID(first.unresolved_incident_id) for reason in rts.blocking_reasons)
    finally:
        engine.dispose()


def test_demo_seed_refuses_normal_or_production_modes(tmp_path: Path) -> None:
    with __import__('pytest').raises(DemoSeedError):
        seed_demo(Settings(_env_file=None, environment="test", demo_mode=False, database_url=f"sqlite:///{tmp_path/'a.db'}"))
    with __import__('pytest').raises(DemoSeedError):
        seed_demo(_settings(tmp_path, environment="production"))


class _MemoryQdrant:
    def __init__(self) -> None:
        self.points: dict[str, tuple[tuple[float, ...], object, object]] = {}
        self.vector_size = 64
    def recreate_collection(self, *, vector_size: int):
        self.points.clear(); self.vector_size = vector_size
        return QdrantCollectionResult(QdrantAvailability.AVAILABLE, "demo", True, True, vector_size, vector_size, QdrantDistance.COSINE, QdrantDistance.COSINE, True)
    def delete_collection(self):
        self.points.clear(); return QdrantMutationResult(QdrantAvailability.AVAILABLE, True)
    def validate_collection(self, *, vector_size: int):
        return QdrantCollectionResult(QdrantAvailability.AVAILABLE, "demo", True, vector_size == self.vector_size, vector_size, self.vector_size, QdrantDistance.COSINE, QdrantDistance.COSINE)
    def upsert_vector(self, *, evidence_id, machine_id, component_id, evidence_type, vector, session_id=None, incident_id=None):
        del evidence_type, session_id, incident_id
        self.points[str(evidence_id)] = (tuple(vector), machine_id, component_id)
        return QdrantMutationResult(QdrantAvailability.AVAILABLE, True, str(evidence_id))
    def vector_search(self, *, vector, machine_id, component_id, top_k, score_threshold=None):
        hits=[]
        q=tuple(vector)
        qn=math.sqrt(sum(v*v for v in q)) or 1.0
        for evidence_id,(v,mid,cid) in self.points.items():
            if mid != machine_id or (component_id is not None and cid != component_id):
                continue
            vn=math.sqrt(sum(x*x for x in v)) or 1.0
            score=sum(a*b for a,b in zip(q,v,strict=True))/(qn*vn)
            if score_threshold is None or score >= score_threshold:
                hits.append(SemanticIndexHit(__import__('uuid').UUID(evidence_id), score))
        hits.sort(key=lambda h:(-h.score,str(h.evidence_id)))
        return QdrantSearchResult(QdrantAvailability.AVAILABLE, tuple(hits[:top_k]))


def test_demo_semantic_story_uses_derived_index_then_sqlite_hydration(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    seed_demo(settings, reset=True)
    engine, factory, uow_factory = _db(settings)
    try:
        provider = DemoHashEmbeddingProvider()
        qdrant = _MemoryQdrant()
        rebuilt = CanonicalEvidenceIndexingService(uow_factory, provider, qdrant).rebuild_qdrant_index()
        assert rebuilt.state is SemanticRebuildState.REBUILT
        assert rebuilt.indexed >= 2

        result = NaturalLanguageSemanticSearchService(uow_factory, provider, qdrant, settings).search(
            SemanticSearchRequest(query="hydraulic pump pressure slow response whine", component_id=COMPONENT_IDS["hydraulic_pump"], limit=5)
        )
        assert result.available is True
        assert result.results
        assert all(item.classification == "Semantic" for item in result.results)
        assert all(item.machine_id == DEMO_MACHINE_ID for item in result.results)
        source_ids = {item.provenance.get("source_system") for item in result.results}
        assert "demo-history" in source_ids
    finally:
        engine.dispose()


def test_demo_mode_application_startup_seeds_before_serving(tmp_path: Path) -> None:
    database_path = tmp_path / "startup-demo.db"
    code = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    health = client.get('/health')
    assert health.status_code == 200, health.text
    overview = client.get('/api/v1/overview')
    assert overview.status_code == 200, overview.text
    payload = overview.json()
    assert payload['demo_mode'] is True
    assert payload['machine']['asset_code'] == 'EXC-204'
    assert payload['active_session'] is not None
    assert payload['counts']['components'] == 7
"""
    env = os.environ.copy()
    env.update({
        "MINE_TRACE_ENVIRONMENT": "test",
        "MINE_TRACE_DEMO_MODE": "true",
        "MINE_TRACE_DATABASE_URL": f"sqlite:///{database_path}",
        "MINE_TRACE_SQLITE_WAL_ENABLED": "false",
        "MINE_TRACE_AI_ENABLED": "false",
    })
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
