"""Controlled request DTOs for the three MINE-TRACE MVP evidence sources.

There is intentionally no generalized adapter/request base class exposed as part
of the API. The three source contracts are explicit and source type itself is
owned by the backend route/service rather than supplied by callers.
"""

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from app.schemas.evidence_context import EvidenceAttachmentInput, ContextSnapshotInput

NonEmptyString = Annotated[str, Field(min_length=1)]


class MachineEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    component_id: UUID | None = None
    session_id: UUID | None = None
    original_source_record_id: NonEmptyString
    original_timestamp: AwareDatetime
    event_type: NonEmptyString
    payload: dict[str, JsonValue]
    raw_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    context_snapshot: ContextSnapshotInput | None = None
    attachments: list[EvidenceAttachmentInput] = Field(default_factory=list)


class MaintenanceRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    component_id: UUID | None = None
    session_id: UUID | None = None
    original_source_record_id: NonEmptyString
    original_timestamp: AwareDatetime
    record_type: NonEmptyString
    payload: dict[str, JsonValue]
    raw_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    context_snapshot: ContextSnapshotInput | None = None
    attachments: list[EvidenceAttachmentInput] = Field(default_factory=list)


class HumanObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    component_id: UUID | None = None
    session_id: UUID | None = None
    original_source_record_id: NonEmptyString
    original_timestamp: AwareDatetime
    observation_type: NonEmptyString
    payload: dict[str, JsonValue]
    raw_payload: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    context_snapshot: ContextSnapshotInput | None = None
    attachments: list[EvidenceAttachmentInput] = Field(default_factory=list)


class EvidenceIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    session_id: UUID | None = None
    idempotent_replay: bool
