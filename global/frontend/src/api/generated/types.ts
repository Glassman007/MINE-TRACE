// AUTO-GENERATED from src/api/generated/openapi.json. DO NOT EDIT BY HAND.
// Regenerate with: npm run generate:api

export type AIAnalysisFallbackReason = "AI_DISABLED" | "AI_PROVIDER_NOT_CONFIGURED" | "AI_PROVIDER_UNAVAILABLE" | "AI_PROVIDER_ERROR" | "AI_TIMEOUT" | "MALFORMED_OUTPUT" | "UNKNOWN_CITATION" | "PROHIBITED_CLAIM" | "INSUFFICIENT_EVIDENCE"

export type AIAnalysisResult = {
  "fallback"?: DeterministicAIFallback | null;
  "result_type": AIAnalysisResultType;
  "validated_ai"?: ValidatedAIAnalysis | null;
}

export type AIAnalysisResultType = "VALIDATED_AI" | "FALLBACK"

export type AIClaim = {
  "claim_type": AIClaimType;
  "evidence_ids": Array<string>;
  "text": string;
}

export type AIClaimType = "EVENT_OCCURRED" | "OBSERVATION_RECORDED" | "MAINTENANCE_RECORDED" | "VERIFICATION_STARTED" | "VERIFICATION_PASSED" | "VERIFICATION_FAILED" | "RECURRENCE_RECORDED" | "SIMILAR_HISTORY_FOUND" | "CONTEXT_RECORDED" | "STATUS_REPORTED"

export type AnalyticsBucketsResponse = {
  "items": Array<AnalyticsCountBucket>;
}

export type AnalyticsCountBucket = {
  "count": number;
  "key": string;
}

export type AnalyticsSummaryResponse = {
  "completed_verification_runs": number;
  "evidence": number;
  "incidents": number;
  "machines": number;
  "maintenance_actions": number;
  "sessions": number;
  "sync_conflicts_unresolved": number;
  "unresolved_incidents": number;
  "verification_completion_rate"?: number | null;
  "verification_runs": number;
}

export type AnalyticsTrendPoint = {
  "count": number;
  "day": string;
}

export type AnalyticsTrendResponse = {
  "items": Array<AnalyticsTrendPoint>;
}

export type BundleEvidenceItem = {
  "anchor_evidence_id"?: string | null;
  "canonical_event_type": string;
  "canonical_payload": Record<string, JsonValue>;
  "component_id": string | null;
  "deterministic_rule_identifier"?: string | null;
  "evidence_id": string;
  "inclusion_reason": string;
  "ingestion_timestamp": string;
  "machine_id": string;
  "original_source_record_id": string;
  "original_timestamp": string;
  "provenance": Record<string, JsonValue>;
  "raw_source_payload": Record<string, JsonValue>;
  "relationship_type"?: IncidentEvidenceRelationshipType | null;
  "similarity_score"?: number | null;
  "source_classification": EvidenceBundleSourceClassification;
  "source_type": string;
}

export type CapabilityStatus = "AVAILABLE" | "DISABLED" | "UNAVAILABLE"

export type ComponentResponse = {
  "component_type"?: string | null;
  "display_name"?: string | null;
  "id": string;
  "machine_id": string;
  "manufacturer"?: string | null;
  "model"?: string | null;
}

export type ContextDimensionInput = {
  "freshness_basis": string;
  "quality": ContextQuality;
  "value": JsonValue | null;
}

export type ContextQuality = "KNOWN" | "UNKNOWN" | "STALE"

export type ContextSnapshotInput = {
  "environment": ContextDimensionInput;
  "location": ContextDimensionInput;
  "machine_operating_state": ContextDimensionInput;
  "shift": ContextDimensionInput;
  "workload": ContextDimensionInput;
}

export type ContextSnapshotOutput = {
  "context": ContextSnapshotInput;
  "evidence_id": string;
  "id": string;
}

export type DeterministicAIFallback = {
  "evidence_bundle_status": EvidenceBundleStatus;
  "exact_history": Array<FallbackEvidenceFact>;
  "incident_id": string;
  "primary_evidence": Array<FallbackEvidenceFact>;
  "reason": AIAnalysisFallbackReason;
  "reason_detail": string;
  "semantic_history": SemanticEnrichmentSummary;
  "verification": Array<FallbackVerificationFact>;
}

export type EvidenceBundleCompleteness = {
  "canonical_readiness_policy": string;
  "incomplete_sections"?: Array<EvidenceBundleSection>;
  "semantic_retrieval": SemanticRetrievalMetadata;
  "status_reason": string;
  "truncated_sections"?: Array<EvidenceBundleSection>;
}

export type EvidenceBundleResponse = {
  "completeness": EvidenceBundleCompleteness;
  "evidence_time_context_snapshots": Array<EvidenceTimeContextItem>;
  "incident_id": string;
  "primary_incident_evidence": Array<BundleEvidenceItem>;
  "provenance_index": Array<ProvenanceIndexItem>;
  "selected_exact_history": Array<BundleEvidenceItem>;
  "selected_semantic_history": Array<BundleEvidenceItem>;
  "status": EvidenceBundleStatus;
  "verification_context": Array<VerificationContextItem>;
}

export type EvidenceBundleSection = "PRIMARY_INCIDENT_EVIDENCE" | "SELECTED_EXACT_HISTORY" | "SELECTED_SEMANTIC_HISTORY" | "VERIFICATION_CONTEXT" | "EVIDENCE_TIME_CONTEXT_SNAPSHOTS" | "PROVENANCE_INDEX"

export type EvidenceBundleSourceClassification = "PRIMARY_INCIDENT_EVIDENCE" | "EXACT_HISTORY" | "SEMANTIC_HISTORY"

export type EvidenceBundleStatus = "READY" | "PARTIAL" | "INSUFFICIENT_EVIDENCE"

export type EvidenceTimeContextItem = {
  "context_snapshots"?: Array<ContextSnapshotOutput>;
  "evidence_id": string;
  "source_classification": EvidenceBundleSourceClassification;
}

export type FallbackEvidenceFact = {
  "canonical_event_type": string;
  "canonical_payload": Record<string, JsonValue>;
  "component_id": string | null;
  "evidence_id": string;
  "evidence_type": string;
  "machine_id": string;
  "original_timestamp": string;
  "provenance": Record<string, JsonValue>;
  "source_classification": EvidenceBundleSourceClassification;
}

export type FallbackVerificationFact = {
  "completed_at": string | null;
  "evidence_ids"?: Array<string>;
  "result": VerificationRunResult | null;
  "rule_identifier": string | null;
  "rule_name": string | null;
  "rule_type": VerificationRuleType | null;
  "started_at": string;
  "verification_run_id": string;
  "window_ends_at": string | null;
}

export type FleetAIAnalysisRequest = {
  "incident_ids"?: Array<string>;
  "machine_ids"?: Array<string>;
  "prompt": string;
  "semantic_query"?: string | null;
  "semantic_top_k"?: number;
  "session_ids"?: Array<string>;
}

export type FleetAIAnalysisResponse = {
  "citations"?: Array<FleetAICitation>;
  "claims"?: Array<AIClaim>;
  "limitations"?: Array<string>;
  "model"?: string | null;
  "provider"?: string;
  "reason"?: string | null;
  "state": FleetAIState;
  "summary"?: string | null;
}

export type FleetAICitation = {
  "evidence_id": string;
  "provenance": Record<string, JsonValue>;
}

export type FleetAIState = "AVAILABLE" | "DEGRADED"

export type FleetIncidentCollectionResponse = {
  "items": Array<FleetIncidentItem>;
  "limit": number;
  "offset": number;
  "total": number;
}

export type FleetIncidentItem = {
  "component_id"?: string | null;
  "created_at": string;
  "due_state"?: string | null;
  "due_time"?: string | null;
  "first_seen_at"?: string | null;
  "incident_id": string;
  "last_seen_at"?: string | null;
  "machine_id": string;
  "machine_model"?: string | null;
  "owner_ref"?: string | null;
  "severity"?: string | null;
  "site_name"?: string | null;
  "source_report_revision"?: number | null;
  "status": IncidentStatus;
  "updated_at": string;
}

export type FleetMachineCollectionResponse = {
  "items": Array<FleetMachineItem>;
  "limit": number;
  "offset": number;
  "total": number;
}

export type FleetMachineItem = {
  "asset_code"?: string | null;
  "display_name"?: string | null;
  "id": string;
  "latest_acknowledged_at"?: string | null;
  "latest_acknowledgement_status"?: string | null;
  "latest_report_revision"?: number | null;
  "latest_sync_received_at"?: string | null;
  "machine_type"?: string | null;
  "manufacturer"?: string | null;
  "model"?: string | null;
  "site_area"?: string | null;
  "site_name"?: string | null;
}

export type FleetOverviewResponse = {
  "acknowledgement_status_counts": Record<string, number>;
  "fleet_machine_count": number;
  "latest_acknowledged_at"?: string | null;
  "latest_sync_received_at"?: string | null;
  "recent_sessions": Array<FleetSessionItem>;
  "unresolved_incident_count": number;
  "unresolved_sync_conflicts": number;
  "verification_states": Record<string, number>;
}

export type FleetSemanticSearchRequest = {
  "component_id"?: string | null;
  "end"?: string | null;
  "machine_id"?: string | null;
  "machine_type"?: string | null;
  "model"?: string | null;
  "query": string;
  "site"?: string | null;
  "start"?: string | null;
  "top_k"?: number;
}

export type FleetSemanticSearchResponse = {
  "reason"?: string | null;
  "results"?: Array<FleetSemanticSearchResult>;
  "state": SemanticSearchState;
}

export type FleetSemanticSearchResult = {
  "canonical_event_type": string;
  "canonical_payload": Record<string, JsonValue>;
  "component_id": string | null;
  "evidence_id": string;
  "incident_ids": Array<string>;
  "ingestion_timestamp": string;
  "machine_id": string;
  "machine_type": string | null;
  "match_type"?: SemanticMatchType;
  "model": string | null;
  "original_timestamp": string;
  "provenance": Record<string, JsonValue>;
  "session_id": string | null;
  "similarity_score": number;
  "site": string | null;
  "source_type": string;
}

export type FleetSessionItem = {
  "ended_at"?: string | null;
  "ingested_at": string;
  "latest_report_revision": number;
  "machine_id": string;
  "operating_hours"?: number | null;
  "session_id": string;
  "started_at": string;
  "state": string;
  "updated_at": string;
}

export type HTTPValidationError = {
  "detail"?: Array<ValidationError>;
}

export type HealthResponse = {
  "database"?: "ok";
  "database_role"?: "canonical_postgresql";
  "status"?: "ok";
}

export type IncidentAuditAction = "INCIDENT_CREATED" | "EVIDENCE_LINKED" | "EVIDENCE_UNLINKED" | "INCIDENT_SPLIT" | "STATUS_CHANGED" | "OWNER_CHANGED" | "SEVERITY_CHANGED" | "DUE_STATE_CHANGED" | "DUE_TIME_CHANGED" | "RECURRENCE_RECORDED" | "HANDOVER_ACKNOWLEDGED"

export type IncidentAuditOutput = {
  "action": IncidentAuditAction;
  "id": string;
  "occurred_at": string;
  "payload": Record<string, JsonValue>;
}

export type IncidentAuditResponse = {
  "audit_events": Array<IncidentAuditOutput>;
  "incident_id": string;
}

export type IncidentDetailResponse = {
  "audit_events": Array<IncidentAuditOutput>;
  "created_at": string;
  "due_state": string | null;
  "due_time": string | null;
  "incident_id": string;
  "machine_id": string;
  "owner_ref": string | null;
  "severity": string | null;
  "status": IncidentStatus;
  "updated_at": string;
}

export type IncidentEvidenceItem = {
  "canonical_event_type": string;
  "canonical_payload": Record<string, JsonValue>;
  "component_id": string | null;
  "deterministic_rule_identifier": string | null;
  "evidence_id": string;
  "is_active": boolean;
  "link_id": string;
  "link_reason": string;
  "linked_at": string;
  "machine_id": string;
  "original_source_record_id": string;
  "original_timestamp": string;
  "provenance": Record<string, JsonValue>;
  "raw_source_payload": Record<string, JsonValue>;
  "relationship_type": IncidentEvidenceRelationshipType;
  "source_type": string;
  "unlinked_at": string | null;
}

export type IncidentEvidenceRelationshipType = "RELATED" | "RECURRENCE" | "VERIFICATION"

export type IncidentEvidenceResponse = {
  "evidence": Array<IncidentEvidenceItem>;
  "incident_id": string;
}

export type IncidentMaintenanceActionItem = {
  "action_id": string;
  "action_type": string;
  "component_id": string | null;
  "description": string | null;
  "incident_id": string;
  "ingestion_timestamp": string;
  "machine_id": string;
  "original_timestamp": string;
  "provenance": Record<string, JsonValue>;
  "session_id": string | null;
  "source_report_revision": number | null;
}

export type IncidentMaintenanceActionsResponse = {
  "actions": Array<IncidentMaintenanceActionItem>;
  "incident_id": string;
}

export type IncidentStatus = "OPEN" | "VERIFYING" | "VERIFIED" | "RECURRED"

export type JsonValue = unknown

export type MLAICapabilityReport = {
  "ai_provider": OperationalCapability;
  "embedding_provider": OperationalCapability;
  "qdrant_semantic": OperationalCapability;
  "signals": MLAIOperationalSignals;
}

export type MLAIOperationalSignals = {
  "ai_citation_rejections": number;
  "ai_claim_policy_rejections": number;
  "ai_provider_errors": number;
  "ai_provider_successes": number;
  "ai_provider_timeouts": number;
  "ai_schema_rejections": number;
  "embedding_provider_failures": number;
  "embedding_provider_successes": number;
  "fallback_reasons": Record<string, number>;
  "indexing_failures": number;
  "last_qdrant_search_latency_ms"?: number | null;
  "qdrant_connectivity_failures": number;
  "qdrant_search_count": number;
  "qdrant_search_failures": number;
  "stale_qdrant_reference_count": number;
}

export type MachineComponentsResponse = {
  "components": Array<ComponentResponse>;
  "machine_id": string;
}

export type MachineSessionsResponse = {
  "items": Array<FleetSessionItem>;
  "limit": number;
  "machine_id": string;
  "offset": number;
  "total": number;
}

export type MachineSyncHealthItem = {
  "acknowledgement_status"?: string | null;
  "age_seconds"?: number | null;
  "latest_acknowledged_at"?: string | null;
  "latest_receipt_id"?: string | null;
  "latest_received_at"?: string | null;
  "latest_report_revision"?: number | null;
  "latest_session_id"?: string | null;
  "machine_id": string;
  "stale"?: boolean | null;
  "unresolved_conflicts": number;
}

export type MaintenanceQueueItem = {
  "component_id"?: string | null;
  "due_state"?: string | null;
  "due_time"?: string | null;
  "incident_id": string;
  "incident_status": IncidentStatus;
  "latest_maintenance_action_id"?: string | null;
  "latest_maintenance_action_type"?: string | null;
  "latest_maintenance_at"?: string | null;
  "latest_verification_completed_at"?: string | null;
  "latest_verification_result"?: VerificationRunResult | null;
  "latest_verification_run_id"?: string | null;
  "machine_id": string;
  "machine_model"?: string | null;
  "site_name"?: string | null;
  "updated_at": string;
  "verification_required": boolean;
}

export type MaintenanceQueueResponse = {
  "items": Array<MaintenanceQueueItem>;
  "limit": number;
  "offset": number;
  "ordering"?: string;
  "total": number;
}

export type OperationalCapability = {
  "model"?: string | null;
  "provider"?: string | null;
  "reason"?: string | null;
  "status": CapabilityStatus;
  "verified_at"?: string | null;
}

export type OptionalCapabilityState = {
  "reason"?: string | null;
  "status": string;
}

export type OverviewResponse = {
  "components_total": number;
  "incidents_by_status": Record<string, number>;
  "incidents_total": number;
  "machines_total": number;
}

export type ProvenanceIndexItem = {
  "evidence_id": string;
  "original_source_record_id": string;
  "provenance": Record<string, JsonValue>;
  "source_classification": EvidenceBundleSourceClassification;
  "source_type": string;
}

export type SemanticEnrichmentState = "AVAILABLE" | "DISABLED" | "UNAVAILABLE"

export type SemanticEnrichmentSummary = {
  "attempted": boolean;
  "configured": boolean;
  "failure_reasons"?: Array<string>;
  "selected_match_count": number;
  "state": SemanticEnrichmentState;
}

export type SemanticHistoryFailure = "SEMANTIC_SEARCH_DISABLED" | "EMBEDDING_UNAVAILABLE" | "SEMANTIC_INDEX_UNAVAILABLE"

export type SemanticMatchType = "SEMANTIC_SIMILARITY"

export type SemanticRetrievalMetadata = {
  "attempted": boolean;
  "configured": boolean;
  "failed": boolean;
  "failures"?: Array<SemanticHistoryFailure>;
  "queried_primary_evidence_ids"?: Array<string>;
}

export type SemanticSearchState = "AVAILABLE" | "DEGRADED" | "DISABLED"

export type SyncAcknowledgement = {
  "acknowledgement_id": string;
  "canonical_receipt_id"?: string | null;
  "conflict_id"?: string | null;
  "package_id": string;
  "received_at": string;
  "report_revision": number;
  "schema_version": string;
  "session_id": string;
  "source_machine_id": string;
  "status": SyncAcknowledgementStatus;
}

export type SyncAcknowledgementStatus = "ACCEPTED" | "DUPLICATE" | "CONFLICT"

export type SyncConflictCollectionResponse = {
  "items": Array<SyncConflictItem>;
  "limit": number;
  "offset": number;
  "total": number;
}

export type SyncConflictItem = {
  "conflict_id": string;
  "conflict_type": string;
  "detected_at": string;
  "existing_checksum"?: string | null;
  "existing_metadata": Record<string, JsonValue>;
  "existing_receipt_id"?: string | null;
  "existing_report_revision"?: number | null;
  "incoming_checksum"?: string | null;
  "incoming_metadata": Record<string, JsonValue>;
  "incoming_package_id": string;
  "incoming_report_revision": number;
  "resolution_notes"?: string | null;
  "resolution_status": string;
  "resolved_at"?: string | null;
  "session_id": string;
  "source_machine_id": string;
}

export type SyncHealthResponse = {
  "ai": OptionalCapabilityState;
  "canonical_database"?: string;
  "embeddings": OptionalCapabilityState;
  "machines": Array<MachineSyncHealthItem>;
  "semantic": OptionalCapabilityState;
  "stale_after_hours"?: number | null;
  "unresolved_conflicts": number;
}

export type ValidatedAIAnalysis = {
  "claims": Array<AIClaim>;
  "limitations": Array<string>;
  "status"?: "VALIDATED";
  "summary": string;
}

export type ValidationError = {
  "ctx"?: {

};
  "input"?: unknown;
  "loc": Array<string | number>;
  "msg": string;
  "type": string;
}

export type VerificationContextItem = {
  "completed_at": string | null;
  "evidence_ids"?: Array<string>;
  "result": VerificationRunResult | null;
  "rule_identifier": string | null;
  "rule_name": string | null;
  "rule_type": VerificationRuleType | null;
  "started_at": string;
  "verification_rule_id": string;
  "verification_run_id": string;
  "window_ends_at": string | null;
  "window_minutes": number | null;
}

export type VerificationRuleType = "NO_EVENT"

export type VerificationRunResponse = {
  "completed_at"?: string | null;
  "evidence_event_ids": Array<string>;
  "id": string;
  "incident_id": string;
  "original_timestamp"?: string | null;
  "outcome_payload": Record<string, JsonValue>;
  "result"?: VerificationRunResult | null;
  "rule_identifier"?: string | null;
  "rule_name"?: string | null;
  "rule_type"?: VerificationRuleType | null;
  "session_id"?: string | null;
  "source_machine_id": string;
  "source_report_revision"?: number | null;
  "started_at": string;
  "verification_rule_id"?: string | null;
  "window_ends_at"?: string | null;
  "window_minutes"?: number | null;
}

export type VerificationRunResult = "SUCCEEDED" | "RECURRENCE_DETECTED"

export type VerificationRunsResponse = {
  "incident_id": string;
  "runs": Array<VerificationRunResponse>;
}
