"""Read-only access to verification outcomes synchronized from edge machines.

The global backend never starts, evaluates, retries, or decides verification.
It stores and exposes the exact rule metadata, outcome and evidence references
that arrived through the authenticated synchronization contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.time import restore_utc
from app.domain.enums import VerificationRuleType, VerificationRunResult
from app.repositories.unit_of_work import UnitOfWork


class VerificationReadError(RuntimeError):
    """Base error for synchronized verification reads."""


class UnknownVerificationIncidentError(VerificationReadError):
    pass


class UnknownVerificationRunError(VerificationReadError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationRunView:
    id: UUID
    incident_id: UUID
    session_id: UUID | None
    source_machine_id: UUID
    verification_rule_id: UUID | None
    rule_identifier: str | None
    rule_name: str | None
    rule_type: VerificationRuleType | None
    window_minutes: int | None
    result: VerificationRunResult | None
    started_at: datetime
    window_ends_at: datetime | None
    completed_at: datetime | None
    original_timestamp: datetime | None
    source_report_revision: int | None
    outcome_payload: dict
    evidence_event_ids: tuple[UUID, ...]


class VerificationQueryService:
    """Read synchronized verification history without executing edge policy."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def get_run(self, run_id: UUID) -> VerificationRunView:
        with self._uow_factory() as uow:
            run = uow.verification_runs.get(run_id)
            if run is None:
                raise UnknownVerificationRunError(f"unknown verification run: {run_id}")
            return self._view(uow, run)

    def list_for_incident(self, incident_id: UUID) -> tuple[VerificationRunView, ...]:
        with self._uow_factory() as uow:
            if uow.incidents.get(incident_id) is None:
                raise UnknownVerificationIncidentError(f"unknown incident: {incident_id}")
            return tuple(
                self._view(uow, run)
                for run in uow.verification_runs.list_for_incident(incident_id)
            )

    @staticmethod
    def _view(uow: UnitOfWork, run) -> VerificationRunView:
        rule = (
            uow.verification_rules.get(run.verification_rule_id)
            if run.verification_rule_id is not None
            else None
        )
        evidence_ids = tuple(
            item.evidence_event_id
            for item in uow.verification_evidence.list_for_run(run.id)
        )
        return VerificationRunView(
            id=run.id,
            incident_id=run.incident_id,
            session_id=run.session_id,
            source_machine_id=run.source_machine_id,
            verification_rule_id=run.verification_rule_id,
            rule_identifier=run.rule_identifier or (rule.identifier if rule else None),
            rule_name=rule.name if rule else None,
            rule_type=rule.rule_type if rule else None,
            window_minutes=rule.window_minutes if rule else None,
            result=run.result,
            started_at=restore_utc(run.started_at),
            window_ends_at=restore_utc(run.window_ends_at),
            completed_at=restore_utc(run.completed_at),
            original_timestamp=restore_utc(run.original_timestamp),
            source_report_revision=run.source_report_revision,
            outcome_payload=run.outcome_payload,
            evidence_event_ids=evidence_ids,
        )


__all__ = [
    "UnknownVerificationIncidentError",
    "UnknownVerificationRunError",
    "VerificationQueryService",
    "VerificationReadError",
    "VerificationRunView",
]
