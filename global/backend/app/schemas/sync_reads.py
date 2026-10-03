"""Read-only synchronization health/conflict contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class OptionalCapabilityState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    reason: str | None = None


class MachineSyncHealthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: UUID
    latest_session_id: UUID | None = None
    latest_report_revision: int | None = None
    latest_receipt_id: UUID | None = None
    latest_received_at: datetime | None = None
    latest_acknowledged_at: datetime | None = None
    acknowledgement_status: str | None = None
    unresolved_conflicts: int
    age_seconds: float | None = None
    stale: bool | None = None


class SyncHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_database: str = "ok"
    machines: list[MachineSyncHealthItem]
    unresolved_conflicts: int
    semantic: OptionalCapabilityState
    embeddings: OptionalCapabilityState
    ai: OptionalCapabilityState
    stale_after_hours: float | None = None


class SyncConflictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conflict_id: UUID
    source_machine_id: UUID
    session_id: UUID
    incoming_package_id: UUID
    existing_receipt_id: UUID | None = None
    conflict_type: str
    incoming_report_revision: int
    existing_report_revision: int | None = None
    incoming_checksum: str | None = None
    existing_checksum: str | None = None
    incoming_metadata: dict[str, JsonValue]
    existing_metadata: dict[str, JsonValue]
    detected_at: datetime
    resolution_status: str
    resolved_at: datetime | None = None
    resolution_notes: str | None = None


class SyncConflictCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SyncConflictItem]
    total: int
    offset: int
    limit: int
