"""Deterministic, restart-safe incident verification.

The MVP supports one rule: ``NO_EVENT``. A run succeeds when no active recurrence
EvidenceEvent for the incident has an ``original_timestamp`` inside the persisted
verification window. All decisions come from SQLite state and typed configuration;
there are no in-memory timers, sleeps, semantic retrieval, ML, or LLM calls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.core.settings import Settings
from app.core.time import normalize_to_utc
from app.domain.enums import (
    IncidentAuditAction,
    IncidentEvidenceRelationshipType,
    IncidentStatus,
    VerificationRuleType,
    VerificationRunResult,
)
from app.domain.lifecycle import InvalidIncidentTransition, validate_incident_transition
from app.models import (
    EvidenceEventRecord,
    IncidentAuditEventRecord,
    IncidentRecord,
    VerificationEvidenceRecord,
    VerificationRuleRecord,
    VerificationRunRecord,
)
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork, UnitOfWork


class VerificationError(RuntimeError):
    """Base verification error."""


class UnknownVerificationIncidentError(VerificationError):
    pass


class UnknownVerificationRunError(VerificationError):
    pass


class VerificationAlreadyActiveError(VerificationError):
    pass


class VerificationConfigurationMismatchError(VerificationError):
    pass


class UnsupportedVerificationRuleError(VerificationError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationRunView:
    id: UUID
    incident_id: UUID
    verification_rule_id: UUID
    rule_identifier: str
    rule_name: str
    rule_type: VerificationRuleType
    window_minutes: int
    result: VerificationRunResult | None
    started_at: datetime
    window_ends_at: datetime
    completed_at: datetime | None
    evidence_event_ids: tuple[UUID, ...]


class VerificationService:
    """Start, evaluate and inspect persisted verification runs."""

    def __init__(
        self,
        settings: Settings,
        uow_factory: Callable[[], UnitOfWork] = SQLAlchemyUnitOfWork,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def start_verification(
        self,
        incident_id: UUID,
        *,
        started_at: datetime | None = None,
    ) -> VerificationRunView:
        """Transition OPEN/RECURRED -> VERIFYING and persist a frozen NO_EVENT run."""

        start = normalize_to_utc(started_at or self._clock())
        with self._uow_factory() as uow:
            incident = uow.incidents.get(incident_id)
            if incident is None:
                raise UnknownVerificationIncidentError(f"unknown incident: {incident_id}")

            if uow.verification_runs.list_pending_for_incident(incident_id):
                raise VerificationAlreadyActiveError(
                    f"incident already has an active verification run: {incident_id}"
                )

            # This is the authoritative lifecycle gate. In particular it rejects
            # VERIFIED -> VERIFYING and any attempt to bypass OPEN -> VERIFYING.
            validate_incident_transition(incident.status, IncidentStatus.VERIFYING)

            rule = self._get_or_create_no_event_rule(uow)
            assert rule.window_minutes is not None  # enforced for service-created rules
            window_ends_at = start + timedelta(minutes=rule.window_minutes)

            run = VerificationRunRecord(
                id=uuid4(),
                incident_id=incident.id,
                verification_rule_id=rule.id,
                result=None,
                started_at=start,
                window_ends_at=window_ends_at,
                completed_at=None,
            )
            uow.verification_runs.add(run)

            before = incident.status
            incident.status = IncidentStatus.VERIFYING
            incident.updated_at = start
            uow.incident_audit_events.add(
                IncidentAuditEventRecord(
                    id=uuid4(),
                    incident_id=incident.id,
                    action=IncidentAuditAction.STATUS_CHANGED,
                    occurred_at=start,
                    payload={
                        "from_status": before.value,
                        "to_status": IncidentStatus.VERIFYING.value,
                        "reason": "verification started",
                        "verification_run_id": str(run.id),
                        "verification_rule_id": str(rule.id),
                        "verification_rule_identifier": rule.identifier,
                        "verification_rule_type": VerificationRuleType.NO_EVENT.value,
                        "window_ends_at": window_ends_at.isoformat(),
                    },
                )
            )
            uow.flush()
            view = self._view(uow, run, rule)
            uow.commit()
            return view

    def evaluate_due(
        self,
        *,
        as_of: datetime | None = None,
    ) -> tuple[VerificationRunView, ...]:
        """Evaluate every persisted due run in deterministic database order."""

        now = normalize_to_utc(as_of or self._clock())
        with self._uow_factory() as uow:
            results: list[VerificationRunView] = []
            for run in uow.verification_runs.list_due(now):
                results.append(self._evaluate_run_in_uow(uow, run, completed_at=now))
            uow.commit()
            return tuple(results)

    def get_run(self, run_id: UUID) -> VerificationRunView:
        with self._uow_factory() as uow:
            run = uow.verification_runs.get(run_id)
            if run is None:
                raise UnknownVerificationRunError(f"unknown verification run: {run_id}")
            rule = uow.verification_rules.get(run.verification_rule_id)
            if rule is None:
                raise VerificationError(
                    f"verification run references missing rule: {run.verification_rule_id}"
                )
            return self._view(uow, run, rule)

    def list_for_incident(self, incident_id: UUID) -> tuple[VerificationRunView, ...]:
        with self._uow_factory() as uow:
            if uow.incidents.get(incident_id) is None:
                raise UnknownVerificationIncidentError(f"unknown incident: {incident_id}")
            views: list[VerificationRunView] = []
            for run in uow.verification_runs.list_for_incident(incident_id):
                rule = uow.verification_rules.get(run.verification_rule_id)
                if rule is None:
                    raise VerificationError(
                        f"verification run references missing rule: {run.verification_rule_id}"
                    )
                views.append(self._view(uow, run, rule))
            return tuple(views)

    def record_recurrence_in_uow(
        self,
        uow: UnitOfWork,
        *,
        incident: IncidentRecord,
        evidence: EvidenceEventRecord,
    ) -> tuple[UUID, ...]:
        """Persist recurrence evidence against any pending run whose window contains it.

        This method does not commit and does not mutate incident status; the existing
        RecurrenceService owns the VERIFYING/VERIFIED -> RECURRED lifecycle change so
        the recurrence link, verification failure, state mutation and audits remain in
        the ingestion transaction.
        """

        occurrence_time = normalize_to_utc(evidence.original_timestamp)
        completed_at = normalize_to_utc(evidence.ingestion_timestamp)
        completed_runs: list[UUID] = []

        for run in uow.verification_runs.list_pending_for_incident(incident.id):
            if run.window_ends_at is None:
                # Legacy rows created before restart-safe verification cannot be
                # evaluated deterministically; do not invent a window.
                continue
            start = normalize_to_utc(run.started_at)
            end = normalize_to_utc(run.window_ends_at)
            if not (start <= occurrence_time <= end):
                continue

            self._persist_verification_evidence(uow, run.id, evidence.id)
            run.result = VerificationRunResult.RECURRENCE_DETECTED
            run.completed_at = completed_at
            uow.flush()
            completed_runs.append(run.id)

        return tuple(completed_runs)

    def _evaluate_run_in_uow(
        self,
        uow: UnitOfWork,
        run: VerificationRunRecord,
        *,
        completed_at: datetime,
    ) -> VerificationRunView:
        rule = uow.verification_rules.get(run.verification_rule_id)
        if rule is None:
            raise VerificationError(
                f"verification run references missing rule: {run.verification_rule_id}"
            )
        self._validate_no_event_rule(rule)
        if run.window_ends_at is None:
            raise VerificationError(
                f"verification run has no persisted window_ends_at: {run.id}"
            )

        incident = uow.incidents.get(run.incident_id)
        if incident is None:
            raise UnknownVerificationIncidentError(f"unknown incident: {run.incident_id}")

        matching = self._matching_recurrence_evidence(uow, run)
        if matching:
            for evidence in matching:
                self._persist_verification_evidence(uow, run.id, evidence.id)
            run.result = VerificationRunResult.RECURRENCE_DETECTED
            run.completed_at = completed_at

            if incident.status in {IncidentStatus.VERIFYING, IncidentStatus.VERIFIED}:
                validate_incident_transition(incident.status, IncidentStatus.RECURRED)
                before = incident.status
                incident.status = IncidentStatus.RECURRED
                incident.updated_at = completed_at
                self._append_status_audit(
                    uow,
                    incident=incident,
                    before=before,
                    after=IncidentStatus.RECURRED,
                    occurred_at=completed_at,
                    run=run,
                    reason="NO_EVENT verification found recurrence evidence in window",
                )
        else:
            run.result = VerificationRunResult.SUCCEEDED
            run.completed_at = completed_at
            # A later recurrence can legitimately have put the incident into RECURRED
            # after this run's window ended but before a delayed evaluator executes.
            # In that case the historical run succeeds without overwriting current state.
            if incident.status == IncidentStatus.VERIFYING:
                validate_incident_transition(IncidentStatus.VERIFYING, IncidentStatus.VERIFIED)
                incident.status = IncidentStatus.VERIFIED
                incident.updated_at = completed_at
                self._append_status_audit(
                    uow,
                    incident=incident,
                    before=IncidentStatus.VERIFYING,
                    after=IncidentStatus.VERIFIED,
                    occurred_at=completed_at,
                    run=run,
                    reason="NO_EVENT verification window completed without recurrence",
                )

        uow.flush()
        return self._view(uow, run, rule)

    def _matching_recurrence_evidence(
        self,
        uow: UnitOfWork,
        run: VerificationRunRecord,
    ) -> list[EvidenceEventRecord]:
        assert run.window_ends_at is not None
        start = normalize_to_utc(run.started_at)
        end = normalize_to_utc(run.window_ends_at)
        matches: list[EvidenceEventRecord] = []
        for link in uow.incident_evidence_links.list_active_for_incident(run.incident_id):
            if link.relationship_type != IncidentEvidenceRelationshipType.RECURRENCE:
                continue
            evidence = uow.evidence_events.get(link.evidence_event_id)
            if evidence is None:
                raise VerificationError(
                    f"verification candidate link references missing evidence: {link.evidence_event_id}"
                )
            occurred = normalize_to_utc(evidence.original_timestamp)
            if start <= occurred <= end:
                matches.append(evidence)
        matches.sort(
            key=lambda evidence: (
                normalize_to_utc(evidence.original_timestamp),
                evidence.id,
            )
        )
        return matches

    def _persist_verification_evidence(
        self,
        uow: UnitOfWork,
        run_id: UUID,
        evidence_id: UUID,
    ) -> None:
        existing_ids = {
            item.evidence_event_id for item in uow.verification_evidence.list_for_run(run_id)
        }
        if evidence_id in existing_ids:
            return
        uow.verification_evidence.add(
            VerificationEvidenceRecord(
                id=uuid4(),
                verification_run_id=run_id,
                evidence_event_id=evidence_id,
            )
        )

    def _get_or_create_no_event_rule(self, uow: UnitOfWork) -> VerificationRuleRecord:
        identifier = self._settings.verification_rule_identifier
        existing = uow.verification_rules.get_by_identifier(identifier)
        if existing is not None:
            self._validate_no_event_rule(existing)
            if (
                existing.name != self._settings.verification_rule_name
                or existing.window_minutes != self._settings.verification_window_minutes
            ):
                raise VerificationConfigurationMismatchError(
                    "existing verification rule configuration does not match settings; "
                    "use a new rule identifier for a changed rule"
                )
            return existing

        rule = VerificationRuleRecord(
            id=uuid5(NAMESPACE_URL, f"mine-trace-verification:{identifier}"),
            identifier=identifier,
            name=self._settings.verification_rule_name,
            rule_type=VerificationRuleType.NO_EVENT,
            window_minutes=self._settings.verification_window_minutes,
        )
        uow.verification_rules.add(rule)
        uow.flush()
        return rule

    @staticmethod
    def _validate_no_event_rule(rule: VerificationRuleRecord) -> None:
        if rule.rule_type != VerificationRuleType.NO_EVENT:
            raise UnsupportedVerificationRuleError(
                f"unsupported verification rule type: {rule.rule_type}"
            )
        if not rule.identifier or not rule.name or not rule.window_minutes:
            raise VerificationError(
                f"verification rule lacks deterministic configuration: {rule.id}"
            )

    def _view(
        self,
        uow: UnitOfWork,
        run: VerificationRunRecord,
        rule: VerificationRuleRecord,
    ) -> VerificationRunView:
        self._validate_no_event_rule(rule)
        if run.window_ends_at is None:
            raise VerificationError(
                f"verification run has no persisted window_ends_at: {run.id}"
            )
        evidence_ids = tuple(
            item.evidence_event_id
            for item in uow.verification_evidence.list_for_run(run.id)
        )
        assert rule.identifier is not None
        assert rule.name is not None
        assert rule.rule_type is not None
        assert rule.window_minutes is not None
        return VerificationRunView(
            id=run.id,
            incident_id=run.incident_id,
            verification_rule_id=rule.id,
            rule_identifier=rule.identifier,
            rule_name=rule.name,
            rule_type=rule.rule_type,
            window_minutes=rule.window_minutes,
            result=run.result,
            started_at=normalize_to_utc(run.started_at),
            window_ends_at=normalize_to_utc(run.window_ends_at),
            completed_at=(
                normalize_to_utc(run.completed_at) if run.completed_at is not None else None
            ),
            evidence_event_ids=evidence_ids,
        )

    @staticmethod
    def _append_status_audit(
        uow: UnitOfWork,
        *,
        incident: IncidentRecord,
        before: IncidentStatus,
        after: IncidentStatus,
        occurred_at: datetime,
        run: VerificationRunRecord,
        reason: str,
    ) -> None:
        uow.incident_audit_events.add(
            IncidentAuditEventRecord(
                id=uuid4(),
                incident_id=incident.id,
                action=IncidentAuditAction.STATUS_CHANGED,
                occurred_at=occurred_at,
                payload={
                    "from_status": before.value,
                    "to_status": after.value,
                    "reason": reason,
                    "verification_run_id": str(run.id),
                    "verification_rule_id": str(run.verification_rule_id),
                },
            )
        )
