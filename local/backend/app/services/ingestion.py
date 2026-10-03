"""Deterministic controlled ingestion for the three MINE-TRACE MVP sources."""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings, get_settings
from app.core.time import normalize_to_utc
from app.domain.enums import EvidenceSourceType, OperatingSessionState
from app.models import ContextSnapshotRecord, EvidenceAttachmentRecord, EvidenceEventRecord
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.evidence_context import ContextSnapshotInput, EvidenceAttachmentInput
from app.schemas.ingestion import (
    HumanObservationInput,
    MachineEventInput,
    MaintenanceRecordInput,
)
from app.services.incident_linking import IncidentLinkingService

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Base class for deterministic ingestion failures."""


class UnknownMachineError(IngestionError):
    pass


class UnknownComponentError(IngestionError):
    pass


class UnknownOperatingSessionError(IngestionError):
    pass


class EvidenceSessionStateError(IngestionError):
    pass


class ConfiguredMachineMismatchError(IngestionError):
    pass


class _SemanticIndexer(Protocol):
    def index_evidence(self, evidence_id: UUID) -> bool: ...


class _IngestionInput(Protocol):
    machine_id: UUID
    component_id: UUID | None
    session_id: UUID | None
    original_source_record_id: str
    original_timestamp: datetime
    payload: dict[str, JsonValue]
    raw_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    context_snapshot: ContextSnapshotInput | None
    attachments: list[EvidenceAttachmentInput]




@dataclass(frozen=True, slots=True)
class IngestionResult:
    evidence_id: UUID
    session_id: UUID | None
    idempotent_replay: bool

class IngestionService:
    """Normalize evidence and apply deterministic incident association atomically."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        incident_linking_service: IncidentLinkingService | None = None,
        semantic_history_service: _SemanticIndexer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings or get_settings()
        self._incident_linking_service = (
            incident_linking_service or IncidentLinkingService(self._settings)
        )
        self._semantic_history_service = semantic_history_service

    def ingest_machine_event(self, request: MachineEventInput) -> UUID:
        return self.ingest_machine_event_result(request).evidence_id

    def ingest_machine_event_result(self, request: MachineEventInput) -> IngestionResult:
        return self._ingest(
            request=request,
            source_type=EvidenceSourceType.MACHINE_EVENT,
            canonical_event_type=request.event_type,
        )

    def ingest_maintenance_record(self, request: MaintenanceRecordInput) -> UUID:
        return self.ingest_maintenance_record_result(request).evidence_id

    def ingest_maintenance_record_result(self, request: MaintenanceRecordInput) -> IngestionResult:
        return self._ingest(
            request=request,
            source_type=EvidenceSourceType.MAINTENANCE_RECORD,
            canonical_event_type=request.record_type,
        )

    def ingest_human_observation(self, request: HumanObservationInput) -> UUID:
        return self.ingest_human_observation_result(request).evidence_id

    def ingest_human_observation_result(self, request: HumanObservationInput) -> IngestionResult:
        return self._ingest(
            request=request,
            source_type=EvidenceSourceType.HUMAN_OBSERVATION,
            canonical_event_type=request.observation_type,
        )

    def _ingest(
        self,
        *,
        request: _IngestionInput,
        source_type: EvidenceSourceType,
        canonical_event_type: str,
    ) -> IngestionResult:
        try:
            with self._uow_factory() as uow:
                self._resolve_controlled_identities(uow, request)

                existing = uow.evidence_events.get_by_source_identity(
                    source_type.value,
                    request.original_source_record_id,
                )
                if existing is not None:
                    return IngestionResult(existing.id, existing.session_id, True)

                evidence_id = uuid4()
                evidence_record = EvidenceEventRecord(
                    id=evidence_id,
                    machine_id=request.machine_id,
                    component_id=request.component_id,
                    session_id=request.session_id,
                    source_type=source_type.value,
                    original_source_record_id=request.original_source_record_id,
                    original_timestamp=normalize_to_utc(request.original_timestamp),
                    canonical_event_type=canonical_event_type,
                    canonical_payload=request.payload,
                    raw_source_payload=request.raw_payload,
                    provenance=request.provenance,
                )
                uow.evidence_events.add(evidence_record)
                uow.flush()

                if request.context_snapshot is not None:
                    uow.context_snapshots.add(
                        ContextSnapshotRecord(
                            id=uuid4(),
                            evidence_event_id=evidence_id,
                            # The former aggregate quality is deliberately unused:
                            # each fixed dimension now owns its quality state.
                            quality=None,
                            snapshot_payload=request.context_snapshot.model_dump(mode="json"),
                        )
                    )

                for attachment in request.attachments:
                    uow.evidence_attachments.add(
                        EvidenceAttachmentRecord(
                            id=uuid4(),
                            evidence_event_id=evidence_id,
                            attachment_type=attachment.attachment_type,
                            storage_reference=attachment.storage_reference,
                            mime_type=attachment.mime_type,
                            file_size=attachment.file_size,
                            checksum=attachment.checksum,
                            created_at=normalize_to_utc(attachment.created_at),
                        )
                    )

                # Evidence, historical context, attachments and deterministic
                # incident association form one authoritative ingestion transaction.
                # Duplicate replays return above before this point, so they cannot
                # create another incident/link/audit event.
                uow.flush()
                self._incident_linking_service.link_new_evidence(uow, evidence_record)
                uow.commit()

                # The canonical database is authoritative and is committed before any optional
                # semantic indexing. Derived-index failure must never roll back
                # or invalidate canonical evidence.
                if self._semantic_history_service is not None:
                    try:
                        self._semantic_history_service.index_evidence(evidence_id)
                    except Exception as exc:
                        logger.warning(
                            "post_commit_semantic_indexing_failed",
                            extra={
                                "evidence_id": str(evidence_id),
                                "error": type(exc).__name__,
                            },
                        )
                return IngestionResult(evidence_id, request.session_id, False)
        except IntegrityError:
            # The database uniqueness constraint is the final arbiter for races
            # between concurrent replays. Recover only when this exact source
            # identity now exists; unrelated integrity failures still surface.
            with self._uow_factory() as retry_uow:
                existing = retry_uow.evidence_events.get_by_source_identity(
                    source_type.value,
                    request.original_source_record_id,
                )
                if existing is not None:
                    return IngestionResult(existing.id, existing.session_id, True)
            raise

    def _resolve_controlled_identities(self, uow: UnitOfWork, request: _IngestionInput) -> None:
        if (
            self._settings.local_machine_id is not None
            and request.machine_id != self._settings.local_machine_id
        ):
            raise ConfiguredMachineMismatchError(
                f"evidence machine does not match configured local machine: {request.machine_id}"
            )

        machine = uow.machines.get(request.machine_id)
        if machine is None:
            raise UnknownMachineError(f"unknown machine: {request.machine_id}")

        if request.component_id is not None:
            component = uow.components.get(request.component_id)
            if component is None or component.machine_id != request.machine_id:
                raise UnknownComponentError(
                    f"unknown component for machine: {request.component_id}"
                )

        if request.session_id is not None:
            session = uow.operating_sessions.get(request.session_id)
            if session is None or session.machine_id != request.machine_id:
                raise UnknownOperatingSessionError(
                    f"unknown operating session for machine: {request.session_id}"
                )
            if session.state != OperatingSessionState.OPEN:
                raise EvidenceSessionStateError(
                    f"evidence may only be associated with an open session: {request.session_id}"
                )
