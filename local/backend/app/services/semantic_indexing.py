"""Canonical-evidence -> embedding -> Qdrant indexing pipeline.

The canonical database is always the source of indexing. This service creates
only disposable derived vector state and never writes canonical evidence or
incident lifecycle state. A complete Qdrant loss can therefore be repaired by
rebuilding from canonical evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.integrations.embeddings import EmbeddingProvider, EmbeddingVector
from app.integrations.qdrant import QdrantAvailability, QdrantService
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.semantic_document import SemanticDocument
from app.services.semantic_documents import SemanticDocumentExtractor


class SemanticIndexingState(StrEnum):
    INDEXED = "INDEXED"
    REMOVED = "REMOVED"
    SKIPPED_INELIGIBLE = "SKIPPED_INELIGIBLE"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class SemanticRebuildState(StrEnum):
    REBUILT = "REBUILT"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EvidenceIndexingResult:
    evidence_id: UUID
    state: SemanticIndexingState
    point_id: str | None = None
    reason: str | None = None

    @property
    def indexed(self) -> bool:
        return self.state is SemanticIndexingState.INDEXED


@dataclass(frozen=True, slots=True)
class BatchIndexingResult:
    requested: int
    indexed: int
    skipped: int
    not_found: int
    failed: int
    unavailable: int
    results: tuple[EvidenceIndexingResult, ...]


@dataclass(frozen=True, slots=True)
class QdrantRebuildResult:
    state: SemanticRebuildState
    canonical_records_seen: int
    eligible_documents: int
    indexed: int
    skipped: int
    failed: int
    collection_recreated: bool
    vector_size: int | None = None
    reason: str | None = None


class CanonicalEvidenceIndexingService:
    """Build and rebuild disposable Qdrant state from canonical evidence only."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        embedding_provider: EmbeddingProvider,
        qdrant: QdrantService,
        *,
        extractor: SemanticDocumentExtractor | None = None,
        batch_size: int = 64,
        observability: MLAIObservability | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._qdrant = qdrant
        self._extractor = extractor or SemanticDocumentExtractor()
        self._batch_size = batch_size
        self._observability = observability or get_ml_ai_observability()

    def index_evidence(self, evidence_id: UUID) -> EvidenceIndexingResult:
        """Index one record after re-reading it from canonical storage."""

        return self.batch_index((evidence_id,)).results[0]

    def reindex_evidence(self, evidence_id: UUID) -> EvidenceIndexingResult:
        """Re-read canonical evidence and replace its deterministic Qdrant point."""

        return self.index_evidence(evidence_id)

    def batch_index(self, evidence_ids: Sequence[UUID]) -> BatchIndexingResult:
        """Index unique canonical evidence IDs as one embedding batch when eligible."""

        unique_ids = tuple(dict.fromkeys(evidence_ids))
        if not unique_ids:
            return BatchIndexingResult(0, 0, 0, 0, 0, 0, ())

        documents: list[SemanticDocument] = []
        results_by_id: dict[UUID, EvidenceIndexingResult] = {}
        with self._uow_factory() as uow:
            for evidence_id in unique_ids:
                evidence = uow.evidence_events.get(evidence_id)
                if evidence is None:
                    results_by_id[evidence_id] = EvidenceIndexingResult(
                        evidence_id, SemanticIndexingState.NOT_FOUND, reason="canonical_evidence_not_found"
                    )
                    continue
                document = self._extractor.extract(evidence)
                if document is None:
                    results_by_id[evidence_id] = EvidenceIndexingResult(
                        evidence_id,
                        SemanticIndexingState.SKIPPED_INELIGIBLE,
                        reason="no_semantic_text",
                    )
                    continue
                documents.append(self._with_authoritative_incident(uow, document))

        if documents:
            self._embed_and_upsert(documents, results_by_id, initialize=True)

        ordered = tuple(results_by_id[evidence_id] for evidence_id in unique_ids)
        summary = self._summarize_batch(ordered)
        self._observability.record_indexing_failure(summary.failed + summary.unavailable)
        return summary

    def remove_derived_vector(self, evidence_id: UUID) -> EvidenceIndexingResult:
        """Remove Qdrant state only. Canonical evidence is deliberately not touched."""

        result = self._qdrant.delete_vector(evidence_id=evidence_id)
        if result.availability is QdrantAvailability.UNAVAILABLE:
            self._observability.record_indexing_failure()
            return EvidenceIndexingResult(
                evidence_id,
                SemanticIndexingState.UNAVAILABLE,
                point_id=result.point_id,
                reason=result.reason,
            )
        if not result.succeeded:
            self._observability.record_indexing_failure()
            return EvidenceIndexingResult(
                evidence_id,
                SemanticIndexingState.FAILED,
                point_id=result.point_id,
                reason=result.reason or "qdrant_delete_failed",
            )
        return EvidenceIndexingResult(
            evidence_id,
            SemanticIndexingState.REMOVED,
            point_id=result.point_id,
        )

    def rebuild_qdrant_index(self) -> QdrantRebuildResult:
        """Rebuild the complete disposable Qdrant collection from canonical evidence.

        The first eligible embedding batch is materialized before replacing the
        current collection so vector dimensionality comes from the configured
        model and an embedding outage cannot destroy an otherwise usable derived
        index. Once replacement begins, any partial failure is reported and a
        retry can rebuild again from canonical truth.
        """

        canonical_records_seen, documents = self._read_all_semantic_documents()
        skipped = canonical_records_seen - len(documents)

        if not documents:
            deletion = self._qdrant.delete_collection()
            if deletion.availability is QdrantAvailability.UNAVAILABLE:
                self._observability.record_indexing_failure()
                return QdrantRebuildResult(
                    SemanticRebuildState.UNAVAILABLE,
                    canonical_records_seen,
                    0,
                    0,
                    skipped,
                    0,
                    False,
                    reason=deletion.reason,
                )
            return QdrantRebuildResult(
                SemanticRebuildState.EMPTY,
                canonical_records_seen,
                0,
                0,
                skipped,
                0,
                False,
            )

        first_documents = documents[: self._batch_size]
        try:
            first_vectors = tuple(
                self._embedding_provider.embed_documents(
                    tuple(document.semantic_text for document in first_documents)
                )
            )
            vector_size = self._validate_embedding_batch(first_documents, first_vectors)
        except Exception as exc:
            self._observability.record_indexing_failure(len(first_documents))
            return QdrantRebuildResult(
                SemanticRebuildState.FAILED,
                canonical_records_seen,
                len(documents),
                0,
                skipped,
                len(first_documents),
                False,
                reason=f"embedding_failed:{type(exc).__name__}",
            )

        collection = self._qdrant.recreate_collection(vector_size=vector_size)
        if collection.availability is QdrantAvailability.UNAVAILABLE:
            self._observability.record_indexing_failure()
            return QdrantRebuildResult(
                SemanticRebuildState.UNAVAILABLE,
                canonical_records_seen,
                len(documents),
                0,
                skipped,
                0,
                False,
                vector_size,
                collection.reason,
            )
        if not collection.compatible:
            self._observability.record_indexing_failure()
            return QdrantRebuildResult(
                SemanticRebuildState.FAILED,
                canonical_records_seen,
                len(documents),
                0,
                skipped,
                0,
                False,
                vector_size,
                collection.reason or "qdrant_collection_incompatible",
            )

        indexed = 0
        failed = 0
        reason: str | None = None
        availability_failed = False

        indexed_now, failure_count, failure_reason, unavailable = self._upsert_materialized(
            first_documents, first_vectors, expected_vector_size=vector_size
        )
        indexed += indexed_now
        failed += failure_count
        reason = failure_reason
        availability_failed = unavailable

        if failed == 0:
            for start in range(self._batch_size, len(documents), self._batch_size):
                batch = documents[start : start + self._batch_size]
                try:
                    vectors = tuple(
                        self._embedding_provider.embed_documents(
                            tuple(document.semantic_text for document in batch)
                        )
                    )
                    self._validate_embedding_batch(
                        batch, vectors, expected_vector_size=vector_size
                    )
                except Exception as exc:
                    failed += len(batch)
                    reason = f"embedding_failed:{type(exc).__name__}"
                    break
                indexed_now, failure_count, failure_reason, unavailable = (
                    self._upsert_materialized(
                        batch, vectors, expected_vector_size=vector_size
                    )
                )
                indexed += indexed_now
                failed += failure_count
                if failure_count:
                    reason = failure_reason
                    availability_failed = unavailable
                    break

        state = SemanticRebuildState.REBUILT
        if failed:
            # Once rebuild aborts, every eligible document not successfully
            # upserted remains missing from the replacement collection. Count
            # all of them so the result is complete and retryable.
            failed = len(documents) - indexed
            state = (
                SemanticRebuildState.UNAVAILABLE
                if availability_failed and indexed == 0
                else SemanticRebuildState.PARTIAL
            )
        if failed:
            self._observability.record_indexing_failure(failed)
        return QdrantRebuildResult(
            state,
            canonical_records_seen,
            len(documents),
            indexed,
            skipped,
            failed,
            True,
            vector_size,
            reason,
        )

    def _read_all_semantic_documents(self) -> tuple[int, list[SemanticDocument]]:
        documents: list[SemanticDocument] = []
        records_seen = 0
        offset = 0
        while True:
            with self._uow_factory() as uow:
                batch = tuple(
                    uow.evidence_events.list_for_semantic_indexing(
                        offset=offset, limit=self._batch_size
                    )
                )
                batch_documents = []
                for evidence in batch:
                    document = self._extractor.extract(evidence)
                    if document is not None:
                        batch_documents.append(self._with_authoritative_incident(uow, document))
            if not batch:
                break
            records_seen += len(batch)
            documents.extend(batch_documents)
            offset += len(batch)
            if len(batch) < self._batch_size:
                break
        return records_seen, documents

    def _embed_and_upsert(
        self,
        documents: Sequence[SemanticDocument],
        results_by_id: dict[UUID, EvidenceIndexingResult],
        *,
        initialize: bool,
    ) -> None:
        try:
            vectors = tuple(
                self._embedding_provider.embed_documents(
                    tuple(document.semantic_text for document in documents)
                )
            )
            vector_size = self._validate_embedding_batch(documents, vectors)
        except Exception as exc:
            reason = f"embedding_failed:{type(exc).__name__}"
            for document in documents:
                results_by_id[document.evidence_id] = EvidenceIndexingResult(
                    document.evidence_id, SemanticIndexingState.FAILED, reason=reason
                )
            return

        if initialize:
            collection = self._qdrant.initialize_collection(vector_size=vector_size)
            if collection.availability is QdrantAvailability.UNAVAILABLE:
                for document in documents:
                    results_by_id[document.evidence_id] = EvidenceIndexingResult(
                        document.evidence_id,
                        SemanticIndexingState.UNAVAILABLE,
                        reason=collection.reason,
                    )
                return
            if not collection.compatible:
                for document in documents:
                    results_by_id[document.evidence_id] = EvidenceIndexingResult(
                        document.evidence_id,
                        SemanticIndexingState.FAILED,
                        reason=collection.reason or "qdrant_collection_incompatible",
                    )
                return

        for index, (document, vector) in enumerate(zip(documents, vectors, strict=True)):
            mutation = self._qdrant.upsert_vector(
                evidence_id=document.evidence_id,
                machine_id=document.machine_id,
                component_id=document.component_id,
                evidence_type=document.evidence_type,
                vector=vector.values,
                session_id=document.session_id,
                incident_id=document.incident_id,
            )
            if mutation.availability is QdrantAvailability.UNAVAILABLE:
                for remaining in documents[index:]:
                    results_by_id[remaining.evidence_id] = EvidenceIndexingResult(
                        remaining.evidence_id,
                        SemanticIndexingState.UNAVAILABLE,
                        reason=mutation.reason,
                    )
                return
            if not mutation.succeeded:
                results_by_id[document.evidence_id] = EvidenceIndexingResult(
                    document.evidence_id,
                    SemanticIndexingState.FAILED,
                    point_id=mutation.point_id,
                    reason=mutation.reason or "qdrant_upsert_failed",
                )
                continue
            results_by_id[document.evidence_id] = EvidenceIndexingResult(
                document.evidence_id,
                SemanticIndexingState.INDEXED,
                point_id=mutation.point_id,
            )

    def _upsert_materialized(
        self,
        documents: Sequence[SemanticDocument],
        vectors: Sequence[EmbeddingVector],
        *,
        expected_vector_size: int,
    ) -> tuple[int, int, str | None, bool]:
        self._validate_embedding_batch(
            documents, vectors, expected_vector_size=expected_vector_size
        )
        indexed = 0
        for index, (document, vector) in enumerate(zip(documents, vectors, strict=True)):
            result = self._qdrant.upsert_vector(
                evidence_id=document.evidence_id,
                machine_id=document.machine_id,
                component_id=document.component_id,
                evidence_type=document.evidence_type,
                vector=vector.values,
                session_id=document.session_id,
                incident_id=document.incident_id,
            )
            if result.availability is QdrantAvailability.UNAVAILABLE:
                return indexed, len(documents) - index, result.reason, True
            if not result.succeeded:
                return indexed, len(documents) - index, result.reason or "qdrant_upsert_failed", False
            indexed += 1
        return indexed, 0, None, False

    @staticmethod
    def _validate_embedding_batch(
        documents: Sequence[SemanticDocument],
        vectors: Sequence[EmbeddingVector],
        *,
        expected_vector_size: int | None = None,
    ) -> int:
        if len(vectors) != len(documents):
            raise ValueError("embedding batch cardinality mismatch")
        if not vectors:
            raise ValueError("embedding batch must not be empty")
        dimensions = {vector.dimensions for vector in vectors}
        if len(dimensions) != 1:
            raise ValueError("embedding batch dimensions are inconsistent")
        vector_size = next(iter(dimensions))
        if expected_vector_size is not None and vector_size != expected_vector_size:
            raise ValueError("embedding dimension changed during indexing")
        return vector_size

    @staticmethod
    def _with_authoritative_incident(uow: UnitOfWork, document: SemanticDocument) -> SemanticDocument:
        links = tuple(uow.incident_evidence_links.list_active_for_evidence(document.evidence_id))
        incident_id = links[0].incident_id if len(links) == 1 else None
        return document.model_copy(update={"incident_id": incident_id})

    @staticmethod
    def _summarize_batch(
        results: Sequence[EvidenceIndexingResult],
    ) -> BatchIndexingResult:
        return BatchIndexingResult(
            requested=len(results),
            indexed=sum(result.state is SemanticIndexingState.INDEXED for result in results),
            skipped=sum(
                result.state is SemanticIndexingState.SKIPPED_INELIGIBLE
                for result in results
            ),
            not_found=sum(result.state is SemanticIndexingState.NOT_FOUND for result in results),
            failed=sum(result.state is SemanticIndexingState.FAILED for result in results),
            unavailable=sum(
                result.state is SemanticIndexingState.UNAVAILABLE for result in results
            ),
            results=tuple(results),
        )


__all__ = [
    "BatchIndexingResult",
    "CanonicalEvidenceIndexingService",
    "EvidenceIndexingResult",
    "QdrantRebuildResult",
    "SemanticIndexingState",
    "SemanticRebuildState",
]
