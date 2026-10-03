from __future__ import annotations

from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.core.time import restore_utc
from app.integrations.embeddings import EmbeddingProvider
from app.integrations.qdrant import QdrantAvailability, QdrantService
from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord, MachineRecord
from app.schemas.semantic_search import (
    FleetSemanticSearchRequest,
    FleetSemanticSearchResponse,
    FleetSemanticSearchResult,
    SemanticSearchState,
)


class FleetSemanticSearchService:
    """Fleet-wide semantic retrieval with mandatory PostgreSQL hydration."""

    def __init__(self, session: Session, embedding: EmbeddingProvider, qdrant: QdrantService, settings: Settings) -> None:
        self._session = session
        self._embedding = embedding
        self._qdrant = qdrant
        self._settings = settings

    def search(self, request: FleetSemanticSearchRequest) -> FleetSemanticSearchResponse:
        if not self._settings.semantic_search_enabled:
            return FleetSemanticSearchResponse(state=SemanticSearchState.DISABLED, reason="semantic_search_disabled")
        try:
            vector = self._embedding.embed_query(request.query)
        except Exception:
            return FleetSemanticSearchResponse(state=SemanticSearchState.DEGRADED, reason="embedding_unavailable")

        candidate_limit = min(1000, max(request.top_k, request.top_k * 20))
        try:
            qresult = self._qdrant.vector_search(
                vector=vector.values,
                machine_id=request.machine_id,
                component_id=request.component_id,
                machine_type=request.machine_type,
                model=request.model,
                site=request.site,
                start=request.start,
                end=request.end,
                top_k=candidate_limit,
                score_threshold=self._settings.semantic_score_threshold,
            )
        except Exception:
            return FleetSemanticSearchResponse(state=SemanticSearchState.DEGRADED, reason="semantic_index_unavailable")
        if qresult.availability is QdrantAvailability.UNAVAILABLE:
            return FleetSemanticSearchResponse(state=SemanticSearchState.DEGRADED, reason="semantic_index_unavailable")

        results: list[FleetSemanticSearchResult] = []
        seen: set[UUID] = set()
        for hit in qresult.hits:
            if len(results) >= request.top_k:
                break
            if hit.evidence_id in seen:
                continue
            seen.add(hit.evidence_id)
            evidence = self._session.get(EvidenceEventRecord, hit.evidence_id)
            if evidence is None:
                continue  # stale Qdrant reference
            machine = self._session.get(MachineRecord, evidence.machine_id)
            if machine is None:
                continue
            if request.machine_id is not None and evidence.machine_id != request.machine_id:
                continue
            if request.component_id is not None and evidence.component_id != request.component_id:
                continue
            if request.machine_type is not None and machine.machine_type != request.machine_type:
                continue
            if request.model is not None and machine.model != request.model:
                continue
            if request.site is not None and machine.site_name != request.site:
                continue
            timestamp = restore_utc(evidence.original_timestamp)
            start = request.start
            end = request.end
            if start is not None:
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if timestamp < start:
                    continue
            if end is not None:
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                if timestamp > end:
                    continue
            incident_ids = list(self._session.scalars(
                select(IncidentEvidenceLinkRecord.incident_id)
                .where(
                    IncidentEvidenceLinkRecord.evidence_event_id == evidence.id,
                    IncidentEvidenceLinkRecord.is_active.is_(True),
                )
                .order_by(IncidentEvidenceLinkRecord.incident_id)
            ).all())
            results.append(FleetSemanticSearchResult(
                similarity_score=hit.score,
                evidence_id=evidence.id,
                machine_id=evidence.machine_id,
                component_id=evidence.component_id,
                session_id=evidence.session_id,
                incident_ids=incident_ids,
                machine_type=machine.machine_type,
                model=machine.model,
                site=machine.site_name,
                source_type=evidence.source_type,
                original_timestamp=timestamp,
                ingestion_timestamp=restore_utc(evidence.ingestion_timestamp),
                canonical_event_type=evidence.canonical_event_type,
                canonical_payload=evidence.canonical_payload,
                provenance=evidence.provenance,
            ))
        return FleetSemanticSearchResponse(state=SemanticSearchState.AVAILABLE, results=results)
