"""Deterministic EvidenceBundle construction.

The bundle is a read-only projection. SQLite remains authoritative; semantic
history is optional enrichment and can never establish canonical sufficiency.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from app.core.settings import Settings
from app.core.time import normalize_to_utc, restore_utc
from app.domain.enums import (
    EvidenceBundleSection,
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
)
from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.evidence_bundle import (
    BundleEvidenceItem,
    EvidenceBundleCompleteness,
    EvidenceBundleResponse,
    EvidenceTimeContextItem,
    ProvenanceIndexItem,
    SemanticRetrievalMetadata,
    VerificationContextItem,
)
from app.schemas.evidence_context import ContextSnapshotInput
from app.schemas.semantic_history import SemanticHistoryFailure, SemanticHistoryResponse
from app.services.ml_ai_contracts import SemanticSearchService
from app.schemas.timeline import ContextSnapshotOutput


class EvidenceBundleError(RuntimeError):
    pass


class UnknownEvidenceBundleIncidentError(EvidenceBundleError):
    pass



CANONICAL_READINESS_POLICY = (
    "READY requires at least one active incident evidence link that hydrates to an "
    "authoritative SQLite EvidenceEvent. Exact and semantic history are enrichment "
    "only and cannot establish canonical sufficiency."
)


class EvidenceBundleService:
    """Construct one deterministic evidence bundle for an incident."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
        semantic_history: SemanticSearchService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._semantic_history = semantic_history

    def build(self, incident_id: UUID) -> EvidenceBundleResponse:
        incomplete: list[EvidenceBundleSection] = []
        truncated: list[EvidenceBundleSection] = []

        with self._uow_factory() as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise UnknownEvidenceBundleIncidentError(
                    f"unknown incident: {incident_id}"
                )

            primary_records: list[tuple[EvidenceEventRecord, IncidentEvidenceLinkRecord]] = []
            missing_primary_reference = False
            for link in uow.incident_evidence_links.list_active_for_incident(incident_id):
                evidence = uow.evidence_events.get(link.evidence_event_id)
                if evidence is None:
                    # The FK should prevent this. Do not turn a broken reference into
                    # usable evidence, but preserve the bundle as partial when another
                    # canonical primary row is still usable.
                    missing_primary_reference = True
                    continue
                primary_records.append((evidence, link))

            primary_records.sort(
                key=lambda pair: (
                    normalize_to_utc(pair[0].original_timestamp),
                    pair[0].id,
                    pair[1].id,
                )
            )
            primary_ids = {record.id for record, _link in primary_records}
            primary_query_ids = [record.id for record, _link in primary_records]

            # Exact history is deterministic, field-based history only:
            # same machine + exact component identity + exact canonical event type +
            # strictly earlier source time within the configured lookback.
            exact_candidates: dict[
                UUID, tuple[EvidenceEventRecord, UUID, float]
            ] = {}
            for primary, _link in primary_records:
                primary_time = normalize_to_utc(primary.original_timestamp)
                history_start = primary_time - timedelta(
                    days=self._settings.history_lookback_days
                )
                candidates = uow.evidence_events.list_machine_timeline(
                    primary.machine_id,
                    start=history_start,
                    end=primary_time,
                )
                for candidate in candidates:
                    if candidate.id in primary_ids:
                        continue
                    candidate_time = normalize_to_utc(candidate.original_timestamp)
                    if candidate_time >= primary_time:
                        continue
                    if candidate.component_id != primary.component_id:
                        continue
                    if candidate.canonical_event_type != primary.canonical_event_type:
                        continue
                    delta_seconds = (primary_time - candidate_time).total_seconds()
                    previous = exact_candidates.get(candidate.id)
                    match = (candidate, primary.id, delta_seconds)
                    if previous is None or (delta_seconds, primary.id) < (
                        previous[2],
                        previous[1],
                    ):
                        exact_candidates[candidate.id] = match

            exact_candidate_ids = set(exact_candidates)
            exact_ordered = sorted(
                exact_candidates.values(),
                key=lambda match: (
                    normalize_to_utc(match[0].original_timestamp),
                    match[0].id,
                ),
            )

            # Primary evidence is never dropped by an enrichment cap. Remaining
            # capacity is consumed by exact history before semantic history.
            historical_capacity = max(
                0, self._settings.evidence_bundle_limit - len(primary_records)
            )
            retained_exact = exact_ordered[:historical_capacity]
            if len(retained_exact) < len(exact_ordered):
                truncated.append(EvidenceBundleSection.SELECTED_EXACT_HISTORY)
            historical_capacity -= len(retained_exact)

            primary_items = [
                self._primary_item(record, link)
                for record, link in primary_records
            ]
            exact_items = [
                self._exact_item(record, anchor_id, delta_seconds)
                for record, anchor_id, delta_seconds in retained_exact
            ]

        semantic_metadata = SemanticRetrievalMetadata(
            configured=self._semantic_history is not None,
            attempted=False,
            failed=False,
        )
        semantic_candidates: dict[
            UUID, tuple[float, UUID]
        ] = {}

        # Semantic history is optional. If it is intentionally not configured,
        # canonical-only bundles can still be READY. If configured retrieval fails,
        # a canonically usable bundle becomes PARTIAL.
        if self._semantic_history is not None and primary_query_ids and historical_capacity > 0:
            semantic_metadata.attempted = True
            for primary_id in primary_query_ids:
                semantic_metadata.queried_primary_evidence_ids.append(primary_id)
                try:
                    response = self._semantic_history.search_similar_history(primary_id)
                except Exception:
                    response = SemanticHistoryResponse(
                        available=False,
                        failure=SemanticHistoryFailure.SEMANTIC_INDEX_UNAVAILABLE,
                    )
                if not response.available:
                    semantic_metadata.failed = True
                    if response.failure is not None and response.failure not in semantic_metadata.failures:
                        semantic_metadata.failures.append(response.failure)
                    continue
                for result in response.results:
                    if result.evidence_id in primary_ids or result.evidence_id in exact_candidate_ids:
                        continue
                    previous = semantic_candidates.get(result.evidence_id)
                    candidate_key = (result.similarity_score, primary_id)
                    if previous is None or candidate_key[0] > previous[0] or (
                        candidate_key[0] == previous[0] and candidate_key[1] < previous[1]
                    ):
                        semantic_candidates[result.evidence_id] = candidate_key

        if semantic_metadata.failed:
            incomplete.append(EvidenceBundleSection.SELECTED_SEMANTIC_HISTORY)

        # Hydrate semantic candidates from SQLite again because the bundle needs the
        # full authoritative EvidenceEvent, not semantic-index payloads.
        semantic_items: list[BundleEvidenceItem] = []
        with self._uow_factory() as uow:
            hydrated_semantic: list[tuple[EvidenceEventRecord, float, UUID]] = []
            for evidence_id, (score, anchor_id) in semantic_candidates.items():
                record = uow.evidence_events.get(evidence_id)
                if record is None:
                    continue
                hydrated_semantic.append((record, score, anchor_id))
            hydrated_semantic.sort(
                key=lambda item: (
                    -item[1],
                    normalize_to_utc(item[0].original_timestamp),
                    item[0].id,
                    item[2],
                )
            )
            retained_semantic = hydrated_semantic[:historical_capacity]
            if len(retained_semantic) < len(hydrated_semantic):
                truncated.append(EvidenceBundleSection.SELECTED_SEMANTIC_HISTORY)
            semantic_items = [
                self._semantic_item(record, score, anchor_id)
                for record, score, anchor_id in retained_semantic
            ]

            retained_items = [*primary_items, *exact_items, *semantic_items]
            retained_ids = [item.evidence_id for item in retained_items]

            verification_context: list[VerificationContextItem] = []
            for run in uow.verification_runs.list_for_incident(incident_id):
                rule = uow.verification_rules.get(run.verification_rule_id)
                if rule is None:
                    raise EvidenceBundleError(
                        f"verification run {run.id} references missing rule "
                        f"{run.verification_rule_id}"
                    )
                verification_evidence_ids = sorted(
                    (
                        row.evidence_event_id
                        for row in uow.verification_evidence.list_for_run(run.id)
                    ),
                    key=str,
                )
                verification_context.append(
                    VerificationContextItem(
                        verification_run_id=run.id,
                        verification_rule_id=rule.id,
                        rule_identifier=rule.identifier,
                        rule_name=rule.name,
                        rule_type=rule.rule_type,
                        window_minutes=rule.window_minutes,
                        result=run.result,
                        started_at=restore_utc(run.started_at),
                        window_ends_at=restore_utc(run.window_ends_at),
                        completed_at=restore_utc(run.completed_at),
                        evidence_ids=verification_evidence_ids,
                    )
                )

            classification_by_id = {
                item.evidence_id: item.source_classification for item in retained_items
            }
            contexts: list[EvidenceTimeContextItem] = []
            for evidence_id in retained_ids:
                snapshots = [
                    ContextSnapshotOutput(
                        id=snapshot.id,
                        evidence_id=snapshot.evidence_event_id,
                        context=ContextSnapshotInput.model_validate(
                            snapshot.snapshot_payload
                        ),
                    )
                    for snapshot in uow.context_snapshots.list_for_evidence(evidence_id)
                ]
                contexts.append(
                    EvidenceTimeContextItem(
                        evidence_id=evidence_id,
                        source_classification=classification_by_id[evidence_id],
                        context_snapshots=snapshots,
                    )
                )

            provenance_index = [
                ProvenanceIndexItem(
                    evidence_id=item.evidence_id,
                    source_classification=item.source_classification,
                    source_type=item.source_type,
                    original_source_record_id=item.original_source_record_id,
                    provenance=item.provenance,
                )
                for item in retained_items
            ]

        if not primary_items:
            status = EvidenceBundleStatus.INSUFFICIENT_EVIDENCE
            if EvidenceBundleSection.PRIMARY_INCIDENT_EVIDENCE not in incomplete:
                incomplete.insert(0, EvidenceBundleSection.PRIMARY_INCIDENT_EVIDENCE)
            status_reason = (
                "No active incident association hydrates to canonical SQLite evidence; "
                "historical or semantic evidence cannot establish bundle sufficiency."
            )
        elif missing_primary_reference or semantic_metadata.failed:
            status = EvidenceBundleStatus.PARTIAL
            if missing_primary_reference and EvidenceBundleSection.PRIMARY_INCIDENT_EVIDENCE not in incomplete:
                incomplete.insert(0, EvidenceBundleSection.PRIMARY_INCIDENT_EVIDENCE)
            status_reason = (
                "Canonical primary evidence is usable, but one or more bundle sections "
                "could not be completed."
            )
        else:
            status = EvidenceBundleStatus.READY
            status_reason = (
                "At least one active canonical primary evidence event is present and "
                "all configured retrieval operations completed successfully."
            )

        return EvidenceBundleResponse(
            incident_id=incident_id,
            status=status,
            primary_incident_evidence=primary_items,
            selected_exact_history=exact_items,
            selected_semantic_history=semantic_items,
            verification_context=verification_context,
            evidence_time_context_snapshots=contexts,
            provenance_index=provenance_index,
            completeness=EvidenceBundleCompleteness(
                canonical_readiness_policy=CANONICAL_READINESS_POLICY,
                status_reason=status_reason,
                incomplete_sections=incomplete,
                truncated_sections=truncated,
                semantic_retrieval=semantic_metadata,
            ),
        )

    @staticmethod
    def _base_item(
        record: EvidenceEventRecord,
        *,
        source_classification: EvidenceBundleSourceClassification,
        inclusion_reason: str,
        relationship_type=None,
        deterministic_rule_identifier: str | None = None,
        similarity_score: float | None = None,
        anchor_evidence_id: UUID | None = None,
    ) -> BundleEvidenceItem:
        return BundleEvidenceItem(
            evidence_id=record.id,
            machine_id=record.machine_id,
            component_id=record.component_id,
            source_type=record.source_type,
            original_source_record_id=record.original_source_record_id,
            original_timestamp=restore_utc(record.original_timestamp),
            ingestion_timestamp=restore_utc(record.ingestion_timestamp),
            canonical_event_type=record.canonical_event_type,
            canonical_payload=record.canonical_payload,
            raw_source_payload=record.raw_source_payload,
            provenance=record.provenance,
            source_classification=source_classification,
            inclusion_reason=inclusion_reason,
            relationship_type=relationship_type,
            deterministic_rule_identifier=deterministic_rule_identifier,
            similarity_score=similarity_score,
            anchor_evidence_id=anchor_evidence_id,
        )

    @classmethod
    def _primary_item(
        cls,
        record: EvidenceEventRecord,
        link: IncidentEvidenceLinkRecord,
    ) -> BundleEvidenceItem:
        return cls._base_item(
            record,
            source_classification=EvidenceBundleSourceClassification.PRIMARY_INCIDENT_EVIDENCE,
            inclusion_reason=(
                f"Active incident association {link.id}: {link.link_reason}"
            ),
            relationship_type=link.relationship_type,
            deterministic_rule_identifier=link.deterministic_rule_identifier,
        )

    @classmethod
    def _exact_item(
        cls,
        record: EvidenceEventRecord,
        anchor_evidence_id: UUID,
        delta_seconds: float,
    ) -> BundleEvidenceItem:
        return cls._base_item(
            record,
            source_classification=EvidenceBundleSourceClassification.EXACT_HISTORY,
            inclusion_reason=(
                "Included by deterministic exact-history policy: same machine, exact "
                "component identity, exact canonical event type, and earlier source "
                f"time within configured lookback; anchor={anchor_evidence_id}; "
                f"delta_seconds={int(delta_seconds)}."
            ),
            anchor_evidence_id=anchor_evidence_id,
        )

    @classmethod
    def _semantic_item(
        cls,
        record: EvidenceEventRecord,
        similarity_score: float,
        anchor_evidence_id: UUID,
    ) -> BundleEvidenceItem:
        return cls._base_item(
            record,
            source_classification=EvidenceBundleSourceClassification.SEMANTIC_HISTORY,
            inclusion_reason=(
                "Included by optional semantic historical retrieval after authoritative "
                f"SQLite hydration; query_anchor={anchor_evidence_id}."
            ),
            similarity_score=similarity_score,
            anchor_evidence_id=anchor_evidence_id,
        )
