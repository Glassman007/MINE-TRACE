from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.capabilities import CapabilityState, CapabilityStatus
from app.core.ml_ai_observability import MLAIObservability
from app.core.settings import Settings
from app.db.base import Base
from app.models import EvidenceEventRecord, SyncReceiptRecord
from app.services.sync_ingestion import GlobalSyncIngestionService
from tests.sync_test_data import signed_envelope


def test_fastembed_initialization_failure_degrades_semantics_not_canonical_ingestion(
    monkeypatch,
) -> None:
    runtime_app = FastAPI()
    runtime_app.state.ml_ai_observability = MLAIObservability()
    runtime_app.state.semantic_retrieval_capability = CapabilityState(
        CapabilityStatus.AVAILABLE, "configured"
    )
    runtime_app.state.embedding_provider_capability = CapabilityState(
        CapabilityStatus.UNAVAILABLE, "configured_unverified"
    )
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            _env_file=None,
            semantic_search_enabled=True,
            qdrant_url="http://qdrant.test:6333",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_dimension=384,
        ),
    )

    def fail_embedding_provider(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("local model cache unavailable")

    monkeypatch.setattr(main_module, "build_embedding_provider", fail_embedding_provider)

    # Optional semantic initialization is contained and does not raise through
    # application startup/health boundaries.
    main_module.initialize_semantic_runtime(runtime_app)

    assert runtime_app.state.semantic_indexing_coordinator is None
    assert runtime_app.state.embedding_provider_capability.status is CapabilityStatus.UNAVAILABLE
    assert runtime_app.state.embedding_provider_capability.reason == "embedding_model_initialization_failed"
    assert runtime_app.state.semantic_retrieval_capability.status is CapabilityStatus.UNAVAILABLE
    assert runtime_app.state.semantic_retrieval_capability.reason == "embedding_model_initialization_failed"

    # Canonical ingestion is independent from local model initialization.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    try:
        with factory() as session:
            result = GlobalSyncIngestionService(session).ingest(signed_envelope())
            assert result.acknowledgement.status.value == "ACCEPTED"

        with factory() as session:
            assert session.scalar(select(func.count()).select_from(SyncReceiptRecord)) == 1
            assert session.scalar(select(func.count()).select_from(EvidenceEventRecord)) == 1
    finally:
        engine.dispose()


def test_semantic_runtime_rejects_existing_qdrant_dimension_mismatch(
    monkeypatch,
) -> None:
    from app.integrations.qdrant import (
        QdrantAvailability,
        QdrantCollectionResult,
        QdrantDistance,
    )

    runtime_app = FastAPI()
    runtime_app.state.ml_ai_observability = MLAIObservability()
    runtime_app.state.semantic_retrieval_capability = CapabilityState(
        CapabilityStatus.AVAILABLE, "configured"
    )
    runtime_app.state.embedding_provider_capability = CapabilityState(
        CapabilityStatus.UNAVAILABLE, "configured_unverified"
    )
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            _env_file=None,
            semantic_search_enabled=True,
            qdrant_url="http://qdrant.test:6333",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_dimension=384,
        ),
    )

    class LocalProvider:
        pass

    class IncompatibleQdrant:
        def initialize_collection(self, *, vector_size: int):
            assert vector_size == 384
            return QdrantCollectionResult(
                availability=QdrantAvailability.AVAILABLE,
                collection_name="mine_trace_evidence",
                exists=True,
                compatible=False,
                expected_vector_size=384,
                actual_vector_size=768,
                expected_distance=QdrantDistance.COSINE,
                actual_distance=QdrantDistance.COSINE,
                reason="vector_size_mismatch",
            )

    monkeypatch.setattr(main_module, "build_embedding_provider", lambda *a, **k: LocalProvider())
    monkeypatch.setattr(
        main_module.QdrantService,
        "from_settings",
        classmethod(lambda cls, *a, **k: IncompatibleQdrant()),
    )

    main_module.initialize_semantic_runtime(runtime_app)

    assert runtime_app.state.semantic_indexing_coordinator is None
    assert runtime_app.state.semantic_retrieval_capability.status is CapabilityStatus.UNAVAILABLE
    assert runtime_app.state.semantic_retrieval_capability.reason == "qdrant_collection_incompatible"
