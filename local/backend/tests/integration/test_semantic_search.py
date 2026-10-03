from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.integrations.embeddings.base import EmbeddingKind, EmbeddingProviderUnavailableError, EmbeddingVector
from app.integrations.qdrant.types import QdrantAvailability, QdrantCollectionResult, QdrantDistance, QdrantSearchResult
from app.integrations.semantic import SemanticIndexHit
from app.models import ComponentRecord, EvidenceEventRecord, MachineRecord
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork
from app.schemas.semantic_search import SemanticSearchFailure, SemanticSearchRequest
from app.services.semantic_search import NaturalLanguageSemanticSearchService


class FakeEmbedding:
    def __init__(self, *, dimension: int = 384, fail: bool = False):
        self.dimension = dimension
        self.fail = fail
        self.queries: list[str] = []

    def embed_query(self, text: str) -> EmbeddingVector:
        self.queries.append(text)
        if self.fail:
            raise EmbeddingProviderUnavailableError("offline model unavailable")
        return EmbeddingVector.validated([0.01] * self.dimension, provider="fake-local", model="fake", kind=EmbeddingKind.QUERY)


class FakeQdrant:
    def __init__(self, hits=(), *, available=True, compatible=True, actual_dimension=384):
        self.hits = tuple(hits)
        self.available = available
        self.compatible = compatible
        self.actual_dimension = actual_dimension
        self.search_calls = []

    def validate_collection(self, *, vector_size: int):
        return QdrantCollectionResult(
            availability=QdrantAvailability.AVAILABLE if self.available else QdrantAvailability.UNAVAILABLE,
            collection_name="local",
            exists=self.available,
            compatible=self.compatible if self.available else False,
            expected_vector_size=vector_size,
            actual_vector_size=self.actual_dimension if self.available else None,
            expected_distance=QdrantDistance.COSINE,
            actual_distance=QdrantDistance.COSINE if self.available else None,
            reason=None if self.available and self.compatible else ("vector_size_mismatch" if self.available else "offline"),
        )

    def vector_search(self, **kwargs):
        self.search_calls.append(kwargs)
        if not self.available:
            return QdrantSearchResult(QdrantAvailability.UNAVAILABLE, reason="offline")
        return QdrantSearchResult(QdrantAvailability.AVAILABLE, hits=self.hits)


def _env(tmp_path: Path):
    machine_id, other_machine_id = uuid4(), uuid4()
    component_id, other_component_id = uuid4(), uuid4()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'semantic.db'}",
        sqlite_wal_enabled=False,
        local_machine_id=machine_id,
        semantic_search_enabled=True,
        qdrant_url="http://127.0.0.1:6333",
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    with factory.begin() as session:
        session.add_all([MachineRecord(id=machine_id), MachineRecord(id=other_machine_id)])
        session.flush()
        session.add_all([
            ComponentRecord(id=component_id, machine_id=machine_id),
            ComponentRecord(id=other_component_id, machine_id=machine_id),
        ])
    return settings, engine, factory, machine_id, other_machine_id, component_id, other_component_id


def _evidence(factory, *, machine_id: UUID, component_id: UUID | None, text: str) -> UUID:
    evidence_id = uuid4()
    with factory.begin() as session:
        session.add(EvidenceEventRecord(
            id=evidence_id,
            machine_id=machine_id,
            component_id=component_id,
            session_id=None,
            source_type="HUMAN_OBSERVATION",
            original_source_record_id=f"src-{evidence_id}",
            original_timestamp=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
            canonical_event_type="INSPECTION_NOTE",
            canonical_payload={"note": text},
            raw_source_payload={"note": text},
            provenance={"source": "test"},
        ))
    return evidence_id


def _service(factory, settings, embedding, qdrant):
    return NaturalLanguageSemanticSearchService(
        lambda: SQLAlchemyUnitOfWork(factory), embedding, qdrant, settings
    )


def test_query_embedding_machine_isolation_and_stale_hydration(tmp_path: Path) -> None:
    settings, engine, factory, machine, other_machine, component, _ = _env(tmp_path)
    local_id = _evidence(factory, machine_id=machine, component_id=component, text="hydraulic leak near pump")
    foreign_id = _evidence(factory, machine_id=other_machine, component_id=None, text="foreign machine")
    stale_id = uuid4()
    embedding = FakeEmbedding()
    qdrant = FakeQdrant([
        SemanticIndexHit(local_id, 0.91),
        SemanticIndexHit(foreign_id, 0.89),
        SemanticIndexHit(stale_id, 0.88),
    ])
    response = _service(factory, settings, embedding, qdrant).search(
        SemanticSearchRequest(query="hydraulic pump leak", limit=10)
    )
    assert response.available is True
    assert [item.evidence_id for item in response.results] == [local_id]
    assert response.results[0].classification == "Semantic"
    assert response.results[0].similarity_score == 0.91
    assert embedding.queries == ["hydraulic pump leak"]
    assert qdrant.search_calls[0]["machine_id"] == machine
    engine.dispose()


def test_component_filter_is_sent_and_rechecked_against_sqlite(tmp_path: Path) -> None:
    settings, engine, factory, machine, _, component, other_component = _env(tmp_path)
    good = _evidence(factory, machine_id=machine, component_id=component, text="good")
    wrong = _evidence(factory, machine_id=machine, component_id=other_component, text="wrong component")
    qdrant = FakeQdrant([SemanticIndexHit(good, 0.9), SemanticIndexHit(wrong, 0.95)])
    response = _service(factory, settings, FakeEmbedding(), qdrant).search(
        SemanticSearchRequest(query="inspection", component_id=component)
    )
    assert [item.evidence_id for item in response.results] == [good]
    assert qdrant.search_calls[0]["component_id"] == component
    engine.dispose()


def test_embedding_and_qdrant_unavailability_are_typed_degraded_states(tmp_path: Path) -> None:
    settings, engine, factory, *_ = _env(tmp_path)
    embedding_failure = _service(factory, settings, FakeEmbedding(fail=True), FakeQdrant()).search(
        SemanticSearchRequest(query="query")
    )
    assert embedding_failure.available is False
    assert embedding_failure.failure is SemanticSearchFailure.EMBEDDING_UNAVAILABLE

    qdrant_failure = _service(factory, settings, FakeEmbedding(), FakeQdrant(available=False)).search(
        SemanticSearchRequest(query="query")
    )
    assert qdrant_failure.available is False
    assert qdrant_failure.failure is SemanticSearchFailure.SEMANTIC_INDEX_UNAVAILABLE
    engine.dispose()


def test_query_or_collection_dimension_mismatch_degrades_semantics(tmp_path: Path) -> None:
    settings, engine, factory, *_ = _env(tmp_path)
    query_bad = _service(factory, settings, FakeEmbedding(dimension=12), FakeQdrant()).search(
        SemanticSearchRequest(query="query")
    )
    assert query_bad.failure is SemanticSearchFailure.DIMENSION_MISMATCH

    collection_bad = _service(
        factory, settings, FakeEmbedding(), FakeQdrant(compatible=False, actual_dimension=12)
    ).search(SemanticSearchRequest(query="query"))
    assert collection_bad.failure is SemanticSearchFailure.DIMENSION_MISMATCH
    engine.dispose()
