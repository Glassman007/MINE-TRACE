from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import IncidentStatus, OperatingSessionState, SessionReportAcknowledgementState, VerificationRunResult


class EvidenceAttachmentManifestReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    storage_reference: str | None = None
    checksum: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class EvidenceManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    machine_id: UUID
    session_id: UUID
    component_id: UUID | None = None
    incident_id: UUID | None = None
    source_type: str
    original_timestamp: datetime
    provenance_reference: str
    checksum: str
    checksum_scope: str = "CANONICAL_EVIDENCE_RECORD"
    storage_references: list[EvidenceAttachmentManifestReference]


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+$")
    entries: list[EvidenceManifestEntry]


class SessionOperatingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    operating_hours: float | None = None
    session_state: OperatingSessionState


class SessionIncidentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    component_id: UUID | None = None
    state: IncidentStatus
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    occurrence_count: int
    severity: str | None = None


class SessionMaintenanceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    component_id: UUID | None = None
    action_type: str
    original_timestamp: datetime
    canonical_payload: dict[str, JsonValue]


class SessionVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_run_id: UUID
    incident_id: UUID
    rule_identifier: str | None = None
    result: VerificationRunResult | None = None
    started_at: datetime
    window_ends_at: datetime | None = None
    completed_at: datetime | None = None
    evidence_event_ids: list[UUID]


class SessionUnresolvedWork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    state: IncidentStatus
    component_id: UUID | None = None


class SessionReportSyncMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_revision: int
    report_revision: int
    acknowledgement_state: SessionReportAcknowledgementState


class MachineSessionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    machine_id: UUID
    session_id: UUID
    schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+$")
    generated_at: datetime
    operating_summary: SessionOperatingSummary
    incident_summaries: list[SessionIncidentSummary]
    maintenance_actions: list[SessionMaintenanceAction]
    verification_results: list[SessionVerificationResult]
    unresolved_work: list[SessionUnresolvedWork]
    evidence_manifest: EvidenceManifest
    sync_metadata: SessionReportSyncMetadata
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_consistent_schema_version(self) -> "MachineSessionReport":
        if self.evidence_manifest.schema_version != self.schema_version:
            raise ValueError("evidence_manifest.schema_version must match report schema_version")
        return self


# Backward-compatible API name retained for existing route/service imports.
MachineSessionReportResponse = MachineSessionReport
