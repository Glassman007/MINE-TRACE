from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import IncidentStatus
from app.schemas.session_reports import EvidenceManifest, MachineSessionReport

_SCHEMA_VERSION_PATTERN = r"^[1-9]\d*\.\d+$"
_CHECKSUM_PATTERN = r"^sha256:[0-9a-f]{64}$"


class IncidentUpdate(BaseModel):
    """Canonical incident state carried with one immutable session snapshot."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN)
    incident_id: UUID
    machine_id: UUID
    component_id: UUID | None = None
    state: IncidentStatus
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    occurrence_count: int = Field(ge=0)
    severity: str | None = None
    report_revision: int = Field(ge=1)


class ImportantTextEvidence(BaseModel):
    """Policy-selected compact textual evidence; never raw high-frequency telemetry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN)
    evidence_id: UUID
    source_type: str
    original_timestamp: datetime
    text: str
    provenance_reference: str


class PolicySelectedRawEvidenceReference(BaseModel):
    """Reference only; raw bytes are not embedded in the normal sync envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN)
    evidence_id: UUID
    storage_reference: str
    checksum: str | None = None
    reason: str


class SyncEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN)
    package_id: UUID
    source_machine_id: UUID
    source_node_id: str | None = None
    session_id: UUID
    local_revision: int = Field(ge=1)
    report_revision: int = Field(ge=1)
    created_at: datetime
    machine_session_report: MachineSessionReport
    incident_updates: list[IncidentUpdate]
    evidence_manifest: EvidenceManifest
    important_text_evidence: list[ImportantTextEvidence] = Field(default_factory=list)
    policy_selected_raw_evidence: list[PolicySelectedRawEvidenceReference] = Field(
        default_factory=list
    )
    checksum: str = Field(pattern=_CHECKSUM_PATTERN)

    @model_validator(mode="after")
    def require_consistent_identity(self) -> "SyncEnvelope":
        report = self.machine_session_report
        if report.schema_version != self.schema_version:
            raise ValueError("machine_session_report.schema_version must match envelope schema_version")
        if self.evidence_manifest.schema_version != self.schema_version:
            raise ValueError("evidence_manifest.schema_version must match envelope schema_version")
        if report.machine_id != self.source_machine_id:
            raise ValueError("machine_session_report.machine_id must match source_machine_id")
        if report.session_id != self.session_id:
            raise ValueError("machine_session_report.session_id must match session_id")
        if report.sync_metadata.local_revision != self.local_revision:
            raise ValueError("report local_revision must match envelope local_revision")
        if report.sync_metadata.report_revision != self.report_revision:
            raise ValueError("report report_revision must match envelope report_revision")
        for update in self.incident_updates:
            if update.schema_version != self.schema_version:
                raise ValueError("incident update schema_version must match envelope schema_version")
            if update.machine_id != self.source_machine_id:
                raise ValueError("incident update machine_id must match source_machine_id")
            if update.report_revision != self.report_revision:
                raise ValueError("incident update report_revision must match envelope report_revision")
        for evidence in self.important_text_evidence:
            if evidence.schema_version != self.schema_version:
                raise ValueError("important text evidence schema_version must match envelope schema_version")
        for evidence in self.policy_selected_raw_evidence:
            if evidence.schema_version != self.schema_version:
                raise ValueError("raw evidence reference schema_version must match envelope schema_version")
        return self


class SyncAcknowledgementStatus(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"


class SyncAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=_SCHEMA_VERSION_PATTERN)
    package_id: UUID
    status: SyncAcknowledgementStatus
    central_revision: int | None = Field(default=None, ge=0)
    acknowledged_at: datetime
    error_code: str | None = None
    message: str | None = None
    resolution_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_conflict_revision(self) -> "SyncAcknowledgement":
        if self.status == SyncAcknowledgementStatus.CONFLICT and self.central_revision is None:
            raise ValueError("central_revision is required for conflict acknowledgement")
        return self


class SyncLatestPackageStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: UUID
    session_id: UUID
    state: str
    local_revision: int
    report_revision: int
    attempt_count: int


class SyncConflictSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: UUID
    package_id: UUID
    object_id: UUID | None = None
    local_revision: int
    central_revision: int
    detected_at: datetime
    state: str
    resolution_metadata: dict[str, JsonValue]


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: UUID
    pending_item_count: int = Field(ge=0)
    failed_item_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    latest_package: SyncLatestPackageStatus | None = None
    last_transmission_attempt: datetime | None = None
    last_acknowledgement: datetime | None = None
    last_error: str | None = None
    transport_configured: bool
    transport_available: bool | None = None
    transport_checked_at: datetime | None = None
    conflicts: list[SyncConflictSummary]
