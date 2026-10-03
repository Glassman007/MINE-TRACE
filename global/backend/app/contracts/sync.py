from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURRENT_SYNC_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SYNC_SCHEMA_MAJORS = frozenset({1})
CHECKSUM_ALGORITHM = "sha256"
_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class SyncContractError(ValueError):
    """Base error for language-neutral synchronization contract failures."""


class UnsupportedSchemaVersionError(SyncContractError):
    pass


class ChecksumMismatchError(SyncContractError):
    pass


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncAcknowledgementStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


class MachineDescriptor(StrictContractModel):
    machine_id: UUID
    asset_code: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    machine_type: str | None = Field(default=None, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    site_name: str | None = Field(default=None, max_length=255)
    site_area: str | None = Field(default=None, max_length=255)


class ComponentDescriptor(StrictContractModel):
    component_id: UUID
    machine_id: UUID
    display_name: str | None = Field(default=None, max_length=255)
    component_type: str | None = Field(default=None, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)


class OperatingSessionSnapshot(StrictContractModel):
    session_id: UUID
    machine_id: UUID
    started_at: datetime
    ended_at: datetime | None = None
    state: str = Field(min_length=1, max_length=64)
    # Decimal is serialized as a JSON string by Pydantic. That avoids binary
    # floating point ambiguity in the cross-language checksum material.
    operating_hours: Decimal | None = Field(default=None, ge=0)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def ended_at_not_before_started_at(self) -> "OperatingSessionSnapshot":
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        return self


class MaintenanceActionSnapshot(StrictContractModel):
    action_id: UUID
    machine_id: UUID
    incident_id: UUID
    session_id: UUID | None = None
    component_id: UUID | None = None
    action_type: str = Field(min_length=1, max_length=128)
    description: str | None = None
    original_timestamp: datetime
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("original_timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("original_timestamp must include a timezone")
        return value


class VerificationRunSnapshot(StrictContractModel):
    verification_run_id: UUID
    incident_id: UUID
    session_id: UUID | None = None
    source_machine_id: UUID
    rule_identifier: str | None = Field(default=None, max_length=255)
    result: Literal["SUCCEEDED", "RECURRENCE_DETECTED"] | None = None
    started_at: datetime
    window_ends_at: datetime | None = None
    completed_at: datetime | None = None
    original_timestamp: datetime | None = None
    outcome_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[UUID] = Field(default_factory=list)

    @field_validator("started_at", "window_ends_at", "completed_at", "original_timestamp")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("verification timestamps must include a timezone")
        return value


class MachineSessionReport(StrictContractModel):
    schema_version: str
    report_id: UUID
    report_revision: int = Field(ge=1)
    generated_at: datetime
    machine: MachineDescriptor
    session: OperatingSessionSnapshot
    components: list[ComponentDescriptor] = Field(default_factory=list)
    maintenance_actions: list[MaintenanceActionSnapshot] = Field(default_factory=list)
    verification_runs: list[VerificationRunSnapshot] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def valid_schema_version(cls, value: str) -> str:
        validate_supported_schema_version(value)
        return value

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value


class EvidenceManifestEntry(StrictContractModel):
    evidence_id: UUID
    source_machine_id: UUID
    session_id: UUID
    component_id: UUID | None = None
    incident_ids: list[UUID] = Field(default_factory=list)
    source_type: str = Field(min_length=1, max_length=100)
    original_source_record_id: str | None = Field(default=None, max_length=255)
    original_timestamp: datetime
    canonical_event_type: str = Field(min_length=1, max_length=100)
    canonical_payload: dict[str, Any]
    provenance: dict[str, Any]
    evidence_checksum: str | None = Field(default=None, max_length=255)

    @field_validator("original_timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("original_timestamp must include a timezone")
        return value


class EvidenceManifest(StrictContractModel):
    schema_version: str
    source_machine_id: UUID
    session_id: UUID
    entries: list[EvidenceManifestEntry] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def valid_schema_version(cls, value: str) -> str:
        validate_supported_schema_version(value)
        return value


class IncidentEvidenceReference(StrictContractModel):
    evidence_id: UUID
    relationship_type: Literal["RELATED", "RECURRENCE", "VERIFICATION"] = "RELATED"
    link_reason: str = Field(default="synchronized_edge_relationship", min_length=1)


class IncidentUpdate(StrictContractModel):
    incident_id: UUID
    machine_id: UUID
    session_id: UUID
    component_id: UUID | None = None
    status: Literal["OPEN", "VERIFYING", "VERIFIED", "RECURRED"]
    severity: str | None = Field(default=None, max_length=64)
    owner_ref: str | None = Field(default=None, max_length=255)
    due_state: str | None = Field(default=None, max_length=64)
    due_time: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    evidence_links: list[IncidentEvidenceReference] = Field(default_factory=list)

    @field_validator("due_time", "first_seen_at", "last_seen_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("incident timestamps must include a timezone")
        return value


class ImportantTextEvidence(StrictContractModel):
    evidence_id: UUID
    semantic_kind: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)


class PolicySelectedRawEvidence(StrictContractModel):
    evidence_id: UUID
    attachment_id: UUID | None = None
    attachment_type: str | None = Field(default=None, max_length=100)
    storage_reference: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=255)
    file_size: int | None = Field(default=None, ge=0)
    checksum: str | None = Field(default=None, max_length=255)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


class SyncMetadata(StrictContractModel):
    checksum_algorithm: str = CHECKSUM_ALGORITHM
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    produced_at: datetime
    producer_version: str | None = Field(default=None, max_length=128)

    @field_validator("checksum_algorithm")
    @classmethod
    def checksum_algorithm_is_locked(cls, value: str) -> str:
        if value != CHECKSUM_ALGORITHM:
            raise ValueError(f"checksum_algorithm must be {CHECKSUM_ALGORITHM}")
        return value

    @field_validator("produced_at")
    @classmethod
    def produced_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("produced_at must include a timezone")
        return value


class SyncEnvelope(StrictContractModel):
    schema_version: str
    package_id: UUID
    source_machine_id: UUID
    session_id: UUID
    report_revision: int = Field(ge=1)
    machine_session_report: MachineSessionReport
    incident_updates: list[IncidentUpdate] = Field(default_factory=list)
    evidence_manifest: EvidenceManifest
    important_text_evidence: list[ImportantTextEvidence] = Field(default_factory=list)
    optional_policy_selected_raw_evidence: list[PolicySelectedRawEvidence] = Field(default_factory=list)
    sync_metadata: SyncMetadata

    @field_validator("schema_version")
    @classmethod
    def valid_schema_version(cls, value: str) -> str:
        validate_supported_schema_version(value)
        return value

    @model_validator(mode="after")
    def identities_must_be_explicit_and_consistent(self) -> "SyncEnvelope":
        report = self.machine_session_report
        manifest = self.evidence_manifest
        if report.schema_version != self.schema_version or manifest.schema_version != self.schema_version:
            raise ValueError("nested schema_version values must match the envelope")
        if report.report_revision != self.report_revision:
            raise ValueError("machine_session_report.report_revision must match report_revision")
        if report.machine.machine_id != self.source_machine_id:
            raise ValueError("report machine identity must match source_machine_id")
        if report.session.machine_id != self.source_machine_id:
            raise ValueError("session machine identity must match source_machine_id")
        if report.session.session_id != self.session_id:
            raise ValueError("report session identity must match session_id")
        if manifest.source_machine_id != self.source_machine_id or manifest.session_id != self.session_id:
            raise ValueError("evidence manifest identity must match envelope identity")

        component_ids = {component.component_id for component in report.components}
        for component in report.components:
            if component.machine_id != self.source_machine_id:
                raise ValueError("all components must belong to source_machine_id")

        evidence_ids = {entry.evidence_id for entry in manifest.entries}
        if len(evidence_ids) != len(manifest.entries):
            raise ValueError("evidence_manifest contains duplicate evidence_id values")
        for entry in manifest.entries:
            if entry.source_machine_id != self.source_machine_id or entry.session_id != self.session_id:
                raise ValueError("all evidence entries must match envelope machine/session")
            if entry.component_id is not None and entry.component_id not in component_ids:
                raise ValueError("evidence component_id must be declared in machine_session_report.components")

        incident_ids = {incident.incident_id for incident in self.incident_updates}
        if len(incident_ids) != len(self.incident_updates):
            raise ValueError("incident_updates contains duplicate incident_id values")
        for incident in self.incident_updates:
            if incident.machine_id != self.source_machine_id or incident.session_id != self.session_id:
                raise ValueError("all incident updates must match envelope machine/session")
            if incident.component_id is not None and incident.component_id not in component_ids:
                raise ValueError("incident component_id must be declared in machine_session_report.components")
            for link in incident.evidence_links:
                if link.evidence_id not in evidence_ids:
                    raise ValueError("incident evidence link must reference evidence_manifest")

        for entry in manifest.entries:
            if any(incident_id not in incident_ids for incident_id in entry.incident_ids):
                raise ValueError("evidence incident_ids must reference incident_updates")

        for action in report.maintenance_actions:
            if action.machine_id != self.source_machine_id:
                raise ValueError("maintenance action machine_id must match source_machine_id")
            if action.session_id not in (None, self.session_id):
                raise ValueError("maintenance action session_id must match session_id")
            if action.incident_id not in incident_ids:
                raise ValueError("maintenance action incident_id must reference incident_updates")
            if action.component_id is not None and action.component_id not in component_ids:
                raise ValueError("maintenance action component_id must be declared")

        for verification in report.verification_runs:
            if verification.source_machine_id != self.source_machine_id:
                raise ValueError("verification source_machine_id must match source_machine_id")
            if verification.session_id not in (None, self.session_id):
                raise ValueError("verification session_id must match session_id")
            if verification.incident_id not in incident_ids:
                raise ValueError("verification incident_id must reference incident_updates")
            if any(evidence_id not in evidence_ids for evidence_id in verification.evidence_ids):
                raise ValueError("verification evidence_ids must reference evidence_manifest")

        important_ids = [item.evidence_id for item in self.important_text_evidence]
        if len(set(important_ids)) != len(important_ids):
            raise ValueError("important_text_evidence contains duplicate evidence_id values")
        if any(evidence_id not in evidence_ids for evidence_id in important_ids):
            raise ValueError("important_text_evidence must reference evidence_manifest")

        raw_ids = [item.evidence_id for item in self.optional_policy_selected_raw_evidence]
        if len(set(raw_ids)) != len(raw_ids):
            raise ValueError("optional_policy_selected_raw_evidence contains duplicate evidence_id values")
        if any(evidence_id not in evidence_ids for evidence_id in raw_ids):
            raise ValueError("raw evidence must reference evidence_manifest")
        return self


class SyncAcknowledgement(StrictContractModel):
    schema_version: str
    acknowledgement_id: UUID
    package_id: UUID
    source_machine_id: UUID
    session_id: UUID
    report_revision: int = Field(ge=1)
    status: SyncAcknowledgementStatus
    received_at: datetime
    canonical_receipt_id: UUID | None = None
    conflict_id: UUID | None = None

    @field_validator("schema_version")
    @classmethod
    def valid_schema_version(cls, value: str) -> str:
        validate_supported_schema_version(value)
        return value

    @field_validator("received_at")
    @classmethod
    def received_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("received_at must include a timezone")
        return value


def schema_major(version: str) -> int:
    match = _SEMVER_PATTERN.fullmatch(version.strip()) if isinstance(version, str) else None
    if not match:
        raise SyncContractError("schema_version must use MAJOR.MINOR.PATCH numeric semver")
    return int(match.group(1))


def validate_supported_schema_version(version: str) -> str:
    major = schema_major(version)
    if major not in SUPPORTED_SYNC_SCHEMA_MAJORS:
        raise UnsupportedSchemaVersionError(f"unsupported sync schema major version: {major}")
    return version


def prevalidate_schema_version(payload: Mapping[str, Any]) -> str:
    """Validate only schema_version before any business fields are interpreted."""

    if not isinstance(payload, Mapping):
        raise SyncContractError("sync payload must be a JSON object")
    version = payload.get("schema_version")
    if not isinstance(version, str):
        raise SyncContractError("schema_version is required and must be a string")
    return validate_supported_schema_version(version)


def parse_sync_envelope(payload: Mapping[str, Any]) -> SyncEnvelope:
    prevalidate_schema_version(payload)
    return SyncEnvelope.model_validate(payload)


def _canonical_decimal(value: Decimal) -> str:
    if value.is_nan() or value.is_infinite():
        raise SyncContractError("non-finite decimal values are not permitted")
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _canonical_float(value: float) -> str:
    """Serialize finite IEEE-754 values with a locked cross-language rule.

    The rule follows ECMAScript/JCS thresholds while using Python's shortest
    round-trippable repr as the significant-digit source.
    """

    if not math.isfinite(value):
        raise SyncContractError("non-finite float values are not permitted")
    if value == 0.0:
        return "0"

    negative = value < 0
    absolute = abs(value)
    shortest = repr(absolute).lower()
    decimal = Decimal(shortest)

    if Decimal("1e-6") <= decimal < Decimal("1e21"):
        text = format(decimal, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"-{text}" if negative else text

    # Scientific form with one non-zero digit before the decimal point,
    # lowercase e, no leading exponent zero, and an explicit '+' for positive
    # exponents. Decimal.normalize() is based on the shortest repr above, so no
    # additional binary->decimal rounding is introduced here.
    normalized = decimal.normalize()
    tup = normalized.as_tuple()
    digits = "".join(str(digit) for digit in tup.digits)
    exponent = tup.exponent + len(digits) - 1
    mantissa = digits[0]
    remainder = digits[1:].rstrip("0")
    if remainder:
        mantissa += "." + remainder
    sign = "+" if exponent >= 0 else ""
    text = f"{mantissa}e{sign}{exponent}"
    return f"-{text}" if negative else text


def _canonical_json(value: Any) -> str:
    if isinstance(value, UUID):
        return json.dumps(str(value).lower(), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SyncContractError("checksum timestamps must include a timezone")
        utc = value.astimezone(timezone.utc)
        timestamp = utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return json.dumps(timestamp, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Decimal):
        # Contract Decimal fields are canonicalized as strings so a producer is
        # never dependent on binary floating-point formatting for those fields.
        return json.dumps(_canonical_decimal(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, StrEnum):
        return json.dumps(value.value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Mapping):
        items: list[str] = []
        for key in sorted(value, key=lambda item: str(item)):
            key_text = json.dumps(str(key), ensure_ascii=False, separators=(",", ":"))
            items.append(f"{key_text}:{_canonical_json(value[key])}")
        return "{" + ",".join(items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    raise SyncContractError(f"unsupported checksum material type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return _canonical_json(value).encode("utf-8")


def checksum_material(envelope: SyncEnvelope) -> dict[str, Any]:
    material = envelope.model_dump(mode="python")
    material["sync_metadata"] = dict(material["sync_metadata"])
    material["sync_metadata"].pop("checksum", None)
    return material


def compute_envelope_checksum(envelope: SyncEnvelope) -> str:
    digest = hashlib.sha256(canonical_json_bytes(checksum_material(envelope))).hexdigest()
    return f"sha256:{digest}"


def validate_envelope_checksum(envelope: SyncEnvelope) -> None:
    supplied = envelope.sync_metadata.checksum
    if not _CHECKSUM_PATTERN.fullmatch(supplied):
        raise ChecksumMismatchError("checksum must use sha256:<lowercase-hex>")
    expected = compute_envelope_checksum(envelope)
    if supplied != expected:
        raise ChecksumMismatchError("sync package checksum mismatch")


def revision_fingerprint_material(envelope: SyncEnvelope) -> dict[str, Any]:
    """Return canonical business content for logical revision idempotency.

    Package transport identity and sync metadata are intentionally excluded so a
    producer may retry identical machine/session/report content under a new
    package_id without duplicating canonical data.
    """

    data = envelope.model_dump(mode="python")
    data.pop("package_id", None)
    data.pop("sync_metadata", None)
    return data


def compute_revision_fingerprint(envelope: SyncEnvelope) -> str:
    digest = hashlib.sha256(canonical_json_bytes(revision_fingerprint_material(envelope))).hexdigest()
    return f"sha256:{digest}"


def with_computed_checksum(envelope: SyncEnvelope) -> SyncEnvelope:
    checksum = compute_envelope_checksum(envelope)
    return envelope.model_copy(
        update={
            "sync_metadata": envelope.sync_metadata.model_copy(update={"checksum": checksum})
        }
    )
