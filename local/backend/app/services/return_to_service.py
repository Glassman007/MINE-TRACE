"""Deterministic return-to-service policy over canonical SQLite state only.

This module deliberately has no dependency on Qdrant, embeddings, semantic
retrieval, LLMs, health percentages, or untyped severity text. Site-specific
DO_NOT_RETURN mappings must be explicitly configured as typed canonical states.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.settings import Settings
from app.domain.enums import ReturnToServiceState
from app.repositories.unit_of_work import SQLAlchemyUnitOfWork, UnitOfWork
from app.schemas.return_to_service import (
    ReturnToServiceBlockingReason,
    ReturnToServiceResponse,
)


class ReturnToServiceConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Reason:
    state: ReturnToServiceState
    code: str
    message: str
    incident_id: UUID
    verification_id: UUID | None
    evidence_ids: tuple[UUID, ...]


class ReturnToServiceService:
    def __init__(
        self,
        settings: Settings,
        uow_factory: Callable[[], UnitOfWork] = SQLAlchemyUnitOfWork,
    ) -> None:
        self._settings = settings
        self._uow_factory = uow_factory

    def evaluate(self) -> ReturnToServiceResponse:
        machine_id = self._settings.local_machine_id
        if machine_id is None:
            raise ReturnToServiceConfigurationError(
                "configured local machine identity is required"
            )

        reasons: list[_Reason] = []
        with self._uow_factory() as uow:
            incidents = tuple(uow.incidents.list_for_machine(machine_id))
            for incident in incidents:
                active_evidence = tuple(
                    sorted(
                        {link.evidence_event_id for link in uow.incident_evidence_links.list_active_for_incident(incident.id)},
                        key=str,
                    )
                )

                if incident.status in self._settings.return_to_service_do_not_return_incident_statuses:
                    reasons.append(
                        _Reason(
                            ReturnToServiceState.DO_NOT_RETURN,
                            "INCIDENT_STATUS_BLOCKS_RETURN",
                            f"incident status {incident.status.value} is configured as return-blocking",
                            incident.id,
                            None,
                            active_evidence,
                        )
                    )
                elif incident.status in self._settings.return_to_service_verification_required_incident_statuses:
                    reasons.append(
                        _Reason(
                            ReturnToServiceState.VERIFICATION_REQUIRED,
                            "INCIDENT_STATUS_REQUIRES_VERIFICATION",
                            f"incident status {incident.status.value} requires verification by configured policy",
                            incident.id,
                            None,
                            active_evidence,
                        )
                    )

                for run in uow.verification_runs.list_for_incident(incident.id):
                    run_evidence = tuple(
                        sorted(
                            {item.evidence_event_id for item in uow.verification_evidence.list_for_run(run.id)},
                            key=str,
                        )
                    )
                    if run.result in self._settings.return_to_service_do_not_return_verification_results:
                        reasons.append(
                            _Reason(
                                ReturnToServiceState.DO_NOT_RETURN,
                                "VERIFICATION_RESULT_BLOCKS_RETURN",
                                f"verification result {run.result.value} is configured as return-blocking",
                                incident.id,
                                run.id,
                                run_evidence or active_evidence,
                            )
                        )
                    elif (
                        self._settings.return_to_service_verification_required_on_pending_run
                        and run.completed_at is None
                    ):
                        reasons.append(
                            _Reason(
                                ReturnToServiceState.VERIFICATION_REQUIRED,
                                "VERIFICATION_RUN_PENDING",
                                "persisted verification run is incomplete",
                                incident.id,
                                run.id,
                                run_evidence or active_evidence,
                            )
                        )

        reasons.sort(
            key=lambda item: (
                0 if item.state is ReturnToServiceState.DO_NOT_RETURN else 1,
                str(item.incident_id),
                str(item.verification_id or ""),
                item.code,
            )
        )
        state = ReturnToServiceState.CLEARED
        if any(item.state is ReturnToServiceState.DO_NOT_RETURN for item in reasons):
            state = ReturnToServiceState.DO_NOT_RETURN
        elif reasons:
            state = ReturnToServiceState.VERIFICATION_REQUIRED

        relevant = [item for item in reasons if item.state is state]
        incident_ids = sorted({item.incident_id for item in relevant}, key=str)
        verification_ids = sorted(
            {item.verification_id for item in relevant if item.verification_id is not None},
            key=str,
        )
        evidence_ids = sorted(
            {evidence_id for item in relevant for evidence_id in item.evidence_ids}, key=str
        )
        return ReturnToServiceResponse(
            state=state,
            blocking_reasons=[
                ReturnToServiceBlockingReason(
                    code=item.code,
                    message=item.message,
                    incident_id=item.incident_id,
                    verification_id=item.verification_id,
                    evidence_ids=list(item.evidence_ids),
                )
                for item in relevant
            ],
            incident_ids=incident_ids,
            verification_ids=verification_ids,
            evidence_ids=evidence_ids,
            policy_identifier=self._settings.return_to_service_policy_identifier,
            policy_revision=self._settings.return_to_service_policy_revision,
        )
