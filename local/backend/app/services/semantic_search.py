"""Natural-language semantic recall with mandatory SQLite hydration."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from app.core.ml_ai_observability import MLAIObservability, get_ml_ai_observability
from app.core.settings import Settings
from app.core.time import restore_utc
from app.integrations.embeddings import EmbeddingProvider
from app.integrations.qdrant import QdrantAvailability, QdrantService
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.semantic_search import (
    SemanticSearchFailure,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResult,
)


class SemanticSearchConfigurationError(RuntimeError):
    pass


class NaturalLanguageSemanticSearchService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        embedding_provider: EmbeddingProvider,
        qdrant: QdrantService,
        settings: Settings,
        *,
        observability: MLAIObservability | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._embedding_provider = embedding_provider
        self._qdrant = qdrant
        self._settings = settings
        self._observability = observability or get_ml_ai_observability()

    def search(self, request: SemanticSearchRequest) -> SemanticSearchResponse:
        if self._settings.local_machine_id is None:
            raise SemanticSearchConfigurationError("configured local machine identity is required")
        if not self._settings.semantic_search_enabled:
            return SemanticSearchResponse(
                available=False,
                failure=SemanticSearchFailure.SEMANTIC_SEARCH_DISABLED,
                reason="semantic search is disabled",
            )

        try:
            vector = self._embedding_provider.embed_query(request.query)
        except Exception as exc:
            return SemanticSearchResponse(
                available=False,
                failure=SemanticSearchFailure.EMBEDDING_UNAVAILABLE,
                reason=f"query_embedding_unavailable:{type(exc).__name__}",
            )

        expected = self._settings.embedding_vector_dimension
        if expected is None or vector.dimensions != expected:
            return SemanticSearchResponse(
                available=False,
                failure=SemanticSearchFailure.DIMENSION_MISMATCH,
                reason=f"query_dimension={vector.dimensions};expected={expected}",
            )

        collection = self._qdrant.validate_collection(vector_size=expected)
        if collection.availability is QdrantAvailability.UNAVAILABLE:
            return SemanticSearchResponse(
                available=False,
                failure=SemanticSearchFailure.SEMANTIC_INDEX_UNAVAILABLE,
                reason=collection.reason,
            )
        if not collection.compatible:
            failure = (
                SemanticSearchFailure.DIMENSION_MISMATCH
                if collection.actual_vector_size is not None
                and collection.actual_vector_size != expected
                else SemanticSearchFailure.SEMANTIC_INDEX_INCOMPATIBLE
            )
            return SemanticSearchResponse(
                available=False,
                failure=failure,
                reason=collection.reason or "semantic collection incompatible",
            )

        search = self._qdrant.vector_search(
            vector=vector.values,
            machine_id=self._settings.local_machine_id,
            component_id=request.component_id,
            top_k=request.limit,
            score_threshold=self._settings.semantic_score_threshold,
        )
        if search.availability is QdrantAvailability.UNAVAILABLE:
            return SemanticSearchResponse(
                available=False,
                failure=SemanticSearchFailure.SEMANTIC_INDEX_UNAVAILABLE,
                reason=search.reason,
            )

        results: list[SemanticSearchResult] = []
        seen: set[UUID] = set()
        with self._uow_factory() as uow:
            for hit in search.hits:
                if len(results) >= request.limit or hit.evidence_id in seen:
                    continue
                seen.add(hit.evidence_id)
                evidence = uow.evidence_events.get(hit.evidence_id)
                if evidence is None:
                    self._observability.record_stale_qdrant_reference()
                    continue
                # Derived metadata can never widen canonical local scope.
                if evidence.machine_id != self._settings.local_machine_id:
                    continue
                if request.component_id is not None and evidence.component_id != request.component_id:
                    continue
                links = tuple(uow.incident_evidence_links.list_active_for_evidence(evidence.id))
                incident_id = links[0].incident_id if len(links) == 1 else None
                results.append(
                    SemanticSearchResult(
                        evidence_id=evidence.id,
                        machine_id=evidence.machine_id,
                        component_id=evidence.component_id,
                        session_id=evidence.session_id,
                        incident_id=incident_id,
                        source_type=evidence.source_type,
                        original_timestamp=restore_utc(evidence.original_timestamp),
                        canonical_event_type=evidence.canonical_event_type,
                        canonical_payload=evidence.canonical_payload,
                        provenance=evidence.provenance,
                        similarity_score=hit.score,
                    )
                )
        return SemanticSearchResponse(available=True, results=results)
