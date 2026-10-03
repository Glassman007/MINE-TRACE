from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord, IncidentRecord, MachineRecord, OperatingSessionRecord
from app.schemas.ai_provider import AIProviderResultStatus
from app.schemas.fleet_ai import FleetAIAnalysisRequest, FleetAIAnalysisResponse, FleetAICitation, FleetAIState
from app.schemas.semantic_search import FleetSemanticSearchRequest, SemanticSearchState


class FleetAIAnalysisService:
    """Read-only orchestration: canonical context -> optional semantic context -> provider."""

    def __init__(self, session: Session, provider: Any, *, model: str | None, semantic_service: Any | None = None) -> None:
        self._session = session
        self._provider = provider
        self._model = model
        self._semantic = semantic_service

    def analyze(self, request: FleetAIAnalysisRequest) -> FleetAIAnalysisResponse:
        canonical = self._build_context(request)
        analyze_fleet = getattr(self._provider, "analyze_fleet", None)
        if not callable(analyze_fleet):
            return FleetAIAnalysisResponse(state=FleetAIState.DEGRADED, model=self._model, reason="groq_provider_unavailable")
        provider_result = analyze_fleet(user_request=request.prompt, canonical_context=canonical)
        if provider_result.status is not AIProviderResultStatus.UNVALIDATED or provider_result.analysis is None:
            return FleetAIAnalysisResponse(
                state=FleetAIState.DEGRADED,
                model=self._model,
                reason=provider_result.reason or provider_result.status.value.lower(),
            )

        analysis = provider_result.analysis
        evidence_by_id = {UUID(row["evidence_id"]): row for row in canonical["evidence"]}
        allowed = set(evidence_by_id)
        for claim in analysis.claims:
            if any(eid not in allowed for eid in claim.evidence_ids):
                return FleetAIAnalysisResponse(state=FleetAIState.DEGRADED, model=self._model, reason="unknown_evidence_citation")

        cited = sorted({eid for claim in analysis.claims for eid in claim.evidence_ids}, key=str)
        return FleetAIAnalysisResponse(
            state=FleetAIState.AVAILABLE,
            model=self._model,
            summary=analysis.summary,
            claims=analysis.claims,
            limitations=analysis.limitations,
            citations=[FleetAICitation(evidence_id=eid, provenance=evidence_by_id[eid]["provenance"]) for eid in cited],
        )

    def _build_context(self, request: FleetAIAnalysisRequest) -> dict[str, Any]:
        machines_stmt = select(MachineRecord)
        if request.machine_ids:
            machines_stmt = machines_stmt.where(MachineRecord.id.in_(request.machine_ids))
        machines = list(self._session.scalars(machines_stmt.order_by(MachineRecord.id).limit(200)).all())

        incidents_stmt = select(IncidentRecord)
        incident_predicates = []
        if request.incident_ids:
            incident_predicates.append(IncidentRecord.id.in_(request.incident_ids))
        if request.machine_ids:
            incident_predicates.append(IncidentRecord.machine_id.in_(request.machine_ids))
        if incident_predicates:
            incidents_stmt = incidents_stmt.where(or_(*incident_predicates))
        elif request.session_ids:
            linked_incidents = select(IncidentEvidenceLinkRecord.incident_id).join(
                EvidenceEventRecord, EvidenceEventRecord.id == IncidentEvidenceLinkRecord.evidence_event_id
            ).where(EvidenceEventRecord.session_id.in_(request.session_ids))
            incidents_stmt = incidents_stmt.where(IncidentRecord.id.in_(linked_incidents))
        incidents = list(self._session.scalars(incidents_stmt.order_by(IncidentRecord.id).limit(200)).all())

        sessions_stmt = select(OperatingSessionRecord)
        session_predicates = []
        if request.session_ids:
            session_predicates.append(OperatingSessionRecord.id.in_(request.session_ids))
        if request.machine_ids:
            session_predicates.append(OperatingSessionRecord.machine_id.in_(request.machine_ids))
        if session_predicates:
            sessions_stmt = sessions_stmt.where(or_(*session_predicates))
        sessions = list(self._session.scalars(sessions_stmt.order_by(OperatingSessionRecord.started_at.desc()).limit(200)).all())

        evidence_ids: set[UUID] = set()
        if incidents:
            evidence_ids.update(self._session.scalars(
                select(IncidentEvidenceLinkRecord.evidence_event_id).where(
                    IncidentEvidenceLinkRecord.incident_id.in_([i.id for i in incidents]),
                    IncidentEvidenceLinkRecord.is_active.is_(True),
                )
            ).all())

        evidence_stmt = select(EvidenceEventRecord)
        predicates = []
        if evidence_ids:
            predicates.append(EvidenceEventRecord.id.in_(evidence_ids))
        if request.machine_ids:
            predicates.append(EvidenceEventRecord.machine_id.in_(request.machine_ids))
        if request.session_ids:
            predicates.append(EvidenceEventRecord.session_id.in_(request.session_ids))
        if predicates:
            evidence_stmt = evidence_stmt.where(or_(*predicates))
        evidence = list(self._session.scalars(evidence_stmt.order_by(EvidenceEventRecord.original_timestamp.desc()).limit(200)).all())

        semantic_note: dict[str, Any] | None = None
        if request.semantic_query and self._semantic is not None:
            semantic_request = FleetSemanticSearchRequest(
                query=request.semantic_query,
                machine_id=request.machine_ids[0] if len(request.machine_ids) == 1 else None,
                top_k=request.semantic_top_k,
            )
            semantic = self._semantic.search(semantic_request)
            semantic_note = {"state": semantic.state.value, "reason": semantic.reason}
            if semantic.state is SemanticSearchState.AVAILABLE:
                existing = {row.id for row in evidence}
                for item in semantic.results:
                    if item.evidence_id not in existing:
                        row = self._session.get(EvidenceEventRecord, item.evidence_id)
                        if row is not None:
                            evidence.append(row)
                            existing.add(row.id)

        machine_by_id = {m.id: m for m in self._session.scalars(select(MachineRecord).where(MachineRecord.id.in_({e.machine_id for e in evidence}))).all()} if evidence else {}
        return {
            "machines": [
                {"machine_id": str(m.id), "display_name": m.display_name, "asset_code": m.asset_code, "machine_type": m.machine_type, "model": m.model, "site": m.site_name}
                for m in machines
            ],
            "sessions": [
                {"session_id": str(s.id), "machine_id": str(s.machine_id), "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None, "state": s.state, "latest_report_revision": s.latest_report_revision}
                for s in sessions
            ],
            "incidents": [
                {"incident_id": str(i.id), "machine_id": str(i.machine_id), "component_id": str(i.component_id) if i.component_id else None, "status": i.status.value if hasattr(i.status, "value") else str(i.status), "severity": i.severity, "first_seen_at": i.first_seen_at.isoformat() if i.first_seen_at else None, "last_seen_at": i.last_seen_at.isoformat() if i.last_seen_at else None}
                for i in incidents
            ],
            "evidence": [
                {"evidence_id": str(e.id), "machine_id": str(e.machine_id), "component_id": str(e.component_id) if e.component_id else None, "session_id": str(e.session_id) if e.session_id else None, "source_type": e.source_type, "original_timestamp": e.original_timestamp.isoformat(), "canonical_event_type": e.canonical_event_type, "canonical_payload": e.canonical_payload, "provenance": e.provenance, "machine_type": machine_by_id.get(e.machine_id).machine_type if machine_by_id.get(e.machine_id) else None, "model": machine_by_id.get(e.machine_id).model if machine_by_id.get(e.machine_id) else None, "site": machine_by_id.get(e.machine_id).site_name if machine_by_id.get(e.machine_id) else None}
                for e in evidence
            ],
            "semantic_retrieval": semantic_note,
        }
