from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from tests.sqlite_test_db import create_sqlite_test_engine
from app.integrations.embeddings import QdrantCloudInferenceEmbeddingProvider
from app.models import EvidenceEventRecord, MachineRecord
from app.services.semantic_documents import SemanticDocumentExtractor


class FixedInferenceClient:
    def embed_documents(self, *, texts, model, timeout_seconds):
        del model, timeout_seconds
        return tuple((float(index + 1), 0.5) for index, _ in enumerate(texts))

    def embed_queries(self, *, texts, model, timeout_seconds):
        del model, timeout_seconds
        return tuple((0.25, float(index + 1)) for index, _ in enumerate(texts))


def test_semantic_extraction_and_embedding_produce_zero_canonical_mutations(tmp_path) -> None:
    settings = Settings(
        environment="test",
    )
    engine = create_sqlite_test_engine(tmp_path / 'semantic-embedding-authority.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    machine_id = uuid4()
    evidence_id = uuid4()
    component_id = None
    occurred_at = datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)
    original_payload = {"observation": "Operator reported pump whine during loaded lift."}
    original_provenance = {"source_system": "authority-test"}

    with factory.begin() as session:
        session.add(MachineRecord(id=machine_id, asset_code="MT-EMBED-001"))
        session.flush()
        session.add(
            EvidenceEventRecord(
                id=evidence_id,
                machine_id=machine_id,
                source_machine_id=machine_id,
                component_id=component_id,
                source_type="HUMAN_OBSERVATION",
                original_source_record_id="authority-obs-001",
                original_timestamp=occurred_at,
                ingestion_timestamp=occurred_at,
                canonical_event_type="OPERATOR_OBSERVATION",
                canonical_payload=original_payload,
                raw_source_payload={"raw": "unchanged"},
                provenance=original_provenance,
            )
        )

    with factory() as session:
        canonical = session.get(EvidenceEventRecord, evidence_id)
        assert canonical is not None
        persisted_timestamp = canonical.original_timestamp
        document = SemanticDocumentExtractor().extract(canonical)
        assert document is not None
        vector = QdrantCloudInferenceEmbeddingProvider(
            model="sentence-transformers/all-minilm-l6-v2",
            timeout_seconds=3,
            client=FixedInferenceClient(),
        ).embed_document(document.semantic_text)
        assert vector.values == (1.0, 0.5)

    with factory() as session:
        unchanged = session.get(EvidenceEventRecord, evidence_id)
        assert unchanged is not None
        assert unchanged.id == evidence_id
        assert unchanged.machine_id == machine_id
        assert unchanged.component_id is component_id
        assert unchanged.canonical_event_type == "OPERATOR_OBSERVATION"
        assert unchanged.canonical_payload == original_payload
        assert unchanged.provenance == original_provenance
        assert unchanged.original_timestamp == persisted_timestamp

    engine.dispose()
