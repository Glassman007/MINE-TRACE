"""Deterministic non-persisted EvidenceBundle response contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.enums import (
    EvidenceBundleSection,
    EvidenceBundleSourceClassification,
    EvidenceBundleStatus,
    IncidentEvidenceRelationshipType,
    VerificationRuleType,
    VerificationRunResult,
)
from app.schemas.semantic_history import SemanticHistoryFailure
from app.schemas.timeline import ContextSnapshotOutput


class BundleEvidenceItem(BaseModel):
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

    source_classification: EvidenceBundleSourceClassification
    inclusion_reason: str
    relationship_type: IncidentEvidenceRelationshipType | None = None
    deterministic_rule_identifier: str | None = None
    similarity_score: float | None = None
    anchor_evidence_id: UUID | None = None


class VerificationContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_run_id: UUID
    verification_rule_id: UUID
    rule_identifier: str | None
    rule_name: str | None
    rule_type: VerificationRuleType | None
    window_minutes: int | None
    result: VerificationRunResult | None
    started_at: datetime
    window_ends_at: datetime | None
    completed_at: datetime | None
    evidence_ids: list[UUID] = Field(default_factory=list)


class EvidenceTimeContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    source_classification: EvidenceBundleSourceClassification
    context_snapshots: list[ContextSnapshotOutput] = Field(default_factory=list)


class ProvenanceIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    source_classification: EvidenceBundleSourceClassification
    source_type: str
    original_source_record_id: str
    provenance: dict[str, JsonValue]


class SemanticRetrievalMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    attempted: bool
    failed: bool
    failures: list[SemanticHistoryFailure] = Field(default_factory=list)
    queried_primary_evidence_ids: list[UUID] = Field(default_factory=list)


class EvidenceBundleCompleteness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_readiness_policy: str
    status_reason: str
    incomplete_sections: list[EvidenceBundleSection] = Field(default_factory=list)
    truncated_sections: list[EvidenceBundleSection] = Field(default_factory=list)
    semantic_retrieval: SemanticRetrievalMetadata


class EvidenceBundleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    status: EvidenceBundleStatus
    primary_incident_evidence: list[BundleEvidenceItem]
    selected_exact_history: list[BundleEvidenceItem]
    selected_semantic_history: list[BundleEvidenceItem]
    verification_context: list[VerificationContextItem]
    evidence_time_context_snapshots: list[EvidenceTimeContextItem]
    provenance_index: list[ProvenanceIndexItem]
    completeness: EvidenceBundleCompleteness
