"""Optional semantic historical retrieval with mandatory canonical hydration.

The retrieval path is deliberately two-tiered:

canonical query evidence -> derived query embedding -> Qdrant candidate IDs ->
canonical evidence hydration -> final semantic-history results.

Qdrant is never treated as evidence authority. Candidate payloads contribute only
an evidence identifier and a derived ranking score. Canonical content,
provenance, timestamps, machine/component identity, and event metadata are read
again from the authoritative repository before any result is returned.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from uuid import UUID

from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.core.settings import Settings
from app.core.time import restore_utc
from app.integrations.embeddings import EmbeddingProvider
from app.integrations.qdrant import QdrantAvailability, QdrantService
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.semantic_history import (
    SemanticHistoryEvidence,
    SemanticHistoryFailure,
    SemanticHistoryResponse,
)
from app.services.semantic_documents import SemanticDocumentExtractor

logger = logging.getLogger(__name__)


class SemanticEvidenceNotFoundError(LookupError):
    pass


class SemanticHistoryService:
    """Retrieve similar historical evidence without granting Qdrant authority.

    The current public query is anchored to one canonical evidence ID because
    EvidenceBundle asks for history relative to primary incident evidence. The
    anchored record is deterministically converted to a ``SemanticDocument`` and
    embedded with ``embed_query``. Qdrant then ranks candidates using the
    configured machine/component filters. Every candidate must survive a second
    canonical hydration and scope check before it can appear in the response.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        embedding_provider: EmbeddingProvider,
        qdrant: QdrantService,
        settings: Settings,
        *,
        extractor: SemanticDocumentExtractor | None = None,
        observability: MLAIObservability | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._qdrant = qdrant
        self._settings = settings
        self._extractor = extractor or SemanticDocumentExtractor()
        self._observability = observability or get_ml_ai_observability()

    def index_evidence(self, evidence_id: UUID) -> bool:
        """Compatibility-only best-effort indexing for legacy ingestion callers.

        CanonicalEvidenceIndexingService is the authoritative indexing pipeline.
        This method remains only so older accepted ingestion wiring does not gain
        a breaking change during the retrieval pass. It still re-reads canonical
        evidence and writes only a disposable Qdrant vector.
        """

        with self._uow_factory() as uow:
            evidence = uow.evidence_events.get(evidence_id)
            if evidence is None:
                raise SemanticEvidenceNotFoundError(f"evidence not found: {evidence_id}")
            document = self._extractor.extract(evidence)

        if document is None:
            return False

        try:
            vector = self._embedding_provider.embed_document(document.semantic_text)
            result = self._qdrant.upsert_vector(
                evidence_id=document.evidence_id,
                machine_id=document.machine_id,
                component_id=document.component_id,
                evidence_type=document.evidence_type,
                vector=vector.values,
            )
        except Exception as exc:  # optional integration must not break canonical flow
            logger.warning(
                "semantic_indexing_failed",
                extra={"evidence_id": str(evidence_id), "error": type(exc).__name__},
            )
            return False

        return result.availability is QdrantAvailability.AVAILABLE and result.succeeded

    def search_similar_history(self, evidence_id: UUID) -> SemanticHistoryResponse:
        """Return Qdrant-ranked candidates hydrated from canonical storage.

        ``similarity_score`` is carried through as derived ranking metadata only.
        It is not confidence, probability, root-cause likelihood, or proof that
        two evidence records describe the same failure.
        """

        if not self._settings.semantic_search_enabled:
            return SemanticHistoryResponse(
                available=False,
                failure=SemanticHistoryFailure.SEMANTIC_SEARCH_DISABLED,
            )

        # Query material itself must originate from canonical storage.
        with self._uow_factory() as uow:
            evidence = uow.evidence_events.get(evidence_id)
            if evidence is None:
                raise SemanticEvidenceNotFoundError(f"evidence not found: {evidence_id}")
            document = self._extractor.extract(evidence)

        # Only human-language evidence is semantically indexed. A canonical row
        # with no eligible text is therefore an honest zero-match query, not an
        # embedding/provider outage.
        if document is None:
            return SemanticHistoryResponse(available=True, results=[])

        try:
            query_vector = self._embedding_provider.embed_query(document.semantic_text)
        except Exception as exc:
            logger.warning(
                "semantic_query_embedding_failed",
                extra={"evidence_id": str(evidence_id), "error": type(exc).__name__},
            )
            return SemanticHistoryResponse(
                available=False,
                failure=SemanticHistoryFailure.EMBEDDING_UNAVAILABLE,
            )

        search = self._qdrant.vector_search(
            vector=query_vector.values,
            machine_id=document.machine_id,
            component_id=document.component_id,
            top_k=self._settings.semantic_top_k,
            score_threshold=self._settings.semantic_score_threshold,
        )
        if search.availability is QdrantAvailability.UNAVAILABLE:
            logger.warning(
                "semantic_index_search_failed",
                extra={"evidence_id": str(evidence_id), "reason": search.reason},
            )
            return SemanticHistoryResponse(
                available=False,
                failure=SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE,
            )

        results: list[SemanticHistoryEvidence] = []
        seen: set[UUID] = set()
        with self._uow_factory() as uow:
            for hit in search.hits:
                # Qdrant can rank at most configured top-K candidate points. A
                # stale/malformed candidate is discarded rather than replaced by
                # fabricated evidence.
                if len(results) >= self._settings.semantic_top_k:
                    break
                if hit.evidence_id == evidence_id or hit.evidence_id in seen:
                    continue
                seen.add(hit.evidence_id)

                # Mandatory canonical hydration. A Qdrant point without a current
                # canonical row is stale derived state and cannot be returned.
                hydrated = uow.evidence_events.get(hit.evidence_id)
                if hydrated is None:
                    self._observability.record_stale_qdrant_reference()
                    continue

                # Re-check scope from canonical truth even though Qdrant already
                # received filters. Stale/malformed Qdrant metadata cannot widen
                # the result set.
                if hydrated.machine_id != document.machine_id:
                    continue
                if (
                    document.component_id is not None
                    and hydrated.component_id != document.component_id
                ):
                    continue

                results.append(
                    SemanticHistoryEvidence(
                        evidence_id=hydrated.id,
                        machine_id=hydrated.machine_id,
                        component_id=hydrated.component_id,
                        evidence_type=hydrated.source_type,
                        original_timestamp=restore_utc(hydrated.original_timestamp),
                        canonical_event_type=hydrated.canonical_event_type,
                        canonical_payload=hydrated.canonical_payload,
                        provenance=hydrated.provenance,
                        similarity_score=hit.score,
                    )
                )

        return SemanticHistoryResponse(available=True, results=results)
