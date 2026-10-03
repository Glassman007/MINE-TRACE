"""Exact historical evidence timeline retrieval."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.core.time import normalize_to_utc, restore_utc
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.evidence_context import ContextSnapshotInput
from app.schemas.timeline import (
    ContextSnapshotOutput,
    EvidenceAttachmentOutput,
    MachineTimelineResponse,
    TimelineEvidenceItem,
)


class TimelineError(RuntimeError):
    """Base class for deterministic timeline query errors."""


class UnknownTimelineMachineError(TimelineError):
    pass


class UnknownTimelineComponentError(TimelineError):
    pass


class InvalidTimelineRangeError(TimelineError):
    pass


class TimelineService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def get_machine_timeline(
        self,
        machine_id: UUID,
        *,
        component_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> MachineTimelineResponse:
        if start is not None and end is not None and start > end:
            raise InvalidTimelineRangeError("from timestamp must be <= to timestamp")

        storage_start = normalize_to_utc(start) if start is not None else None
        storage_end = normalize_to_utc(end) if end is not None else None

        with self._uow_factory() as uow:
            if uow.machines.get(machine_id) is None:
                raise UnknownTimelineMachineError(f"unknown machine: {machine_id}")

            if component_id is not None:
                component = uow.components.get(component_id)
                if component is None or component.machine_id != machine_id:
                    raise UnknownTimelineComponentError(
                        f"unknown component for machine: {component_id}"
                    )

            records = uow.evidence_events.list_machine_timeline(
                machine_id,
                component_id=component_id,
                start=storage_start,
                end=storage_end,
            )

            items: list[TimelineEvidenceItem] = []
            for record in records:
                contexts = [
                    ContextSnapshotOutput(
                        id=snapshot.id,
                        evidence_id=snapshot.evidence_event_id,
                        context=ContextSnapshotInput.model_validate(snapshot.snapshot_payload),
                    )
                    for snapshot in uow.context_snapshots.list_for_evidence(record.id)
                ]
                attachments = [
                    EvidenceAttachmentOutput(
                        id=attachment.id,
                        evidence_id=attachment.evidence_event_id,
                        attachment_type=attachment.attachment_type,
                        storage_reference=attachment.storage_reference,
                        mime_type=attachment.mime_type,
                        file_size=attachment.file_size,
                        checksum=attachment.checksum,
                        created_at=restore_utc(attachment.created_at),
                    )
                    for attachment in uow.evidence_attachments.list_for_evidence(record.id)
                ]
                items.append(
                    TimelineEvidenceItem(
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
                        context_snapshots=contexts,
                        attachments=attachments,
                    )
                )

            return MachineTimelineResponse(
                machine_id=machine_id,
                component_id=component_id,
                from_timestamp=normalize_to_utc(start) if start is not None else None,
                to_timestamp=normalize_to_utc(end) if end is not None else None,
                evidence=items,
            )
