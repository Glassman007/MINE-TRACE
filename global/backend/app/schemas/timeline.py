"""Response contracts for exact historical evidence retrieval."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.schemas.evidence_context import ContextSnapshotInput


class EvidenceAttachmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    evidence_id: UUID
    attachment_type: str | None
    storage_reference: str | None
    mime_type: str | None
    file_size: int | None
    checksum: str | None
    created_at: datetime | None


class ContextSnapshotOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    evidence_id: UUID
    context: ContextSnapshotInput


class TimelineEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    machine_id: UUID
    component_id: UUID | None
    source_type: str
    original_source_record_id: str
    original_timestamp: datetime
    ingestion_timestamp: datetime
    canonical_event_type: str
    canonical_payload: dict[str, JsonValue]
    raw_source_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    context_snapshots: list[ContextSnapshotOutput]
    attachments: list[EvidenceAttachmentOutput]


class MachineTimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    component_id: UUID | None = None
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None
    evidence: list[TimelineEvidenceItem]
