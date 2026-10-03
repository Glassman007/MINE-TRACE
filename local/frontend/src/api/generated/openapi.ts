/* eslint-disable */
/**
 * AUTO-GENERATED from contracts/openapi.json.
 * Do not edit by hand. Run: npm run api:types
 */

export interface components {
  schemas: {
    "AIAnalysisFallbackReason": "AI_DISABLED" | "AI_PROVIDER_NOT_CONFIGURED" | "AI_PROVIDER_UNAVAILABLE" | "AI_PROVIDER_ERROR" | "AI_TIMEOUT" | "MALFORMED_OUTPUT" | "UNKNOWN_CITATION" | "PROHIBITED_CLAIM" | "INSUFFICIENT_EVIDENCE";
    "AIAnalysisResult": {
      "evidence_ids"?: Array<string>;
      "fallback"?: components["schemas"]["DeterministicAIFallback"] | null;
      "incident_id": string;
      "result_type": components["schemas"]["AIAnalysisResultType"];
      "validated_ai"?: components["schemas"]["ValidatedAIAnalysis"] | null;
    };
    "AIAnalysisResultType": "VALIDATED_AI" | "FALLBACK";
    "AIClaim": {
      "claim_type": components["schemas"]["AIClaimType"];
      "evidence_ids": Array<string>;
      "text": string;
    };
    "AIClaimType": "EVENT_OCCURRED" | "OBSERVATION_RECORDED" | "MAINTENANCE_RECORDED" | "VERIFICATION_STARTED" | "VERIFICATION_PASSED" | "VERIFICATION_FAILED" | "RECURRENCE_RECORDED" | "SIMILAR_HISTORY_FOUND" | "CONTEXT_RECORDED" | "STATUS_REPORTED";
    "BundleEvidenceItem": {
      "anchor_evidence_id"?: string | null;
      "canonical_event_type": string;
      "canonical_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "component_id": string | null;
      "deterministic_rule_identifier"?: string | null;
      "evidence_id": string;
      "inclusion_reason": string;
      "ingestion_timestamp": string;
      "machine_id": string;
      "original_source_record_id": string;
      "original_timestamp": string;
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_source_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "relationship_type"?: components["schemas"]["IncidentEvidenceRelationshipType"] | null;
      "similarity_score"?: number | null;
      "source_classification": components["schemas"]["EvidenceBundleSourceClassification"];
      "source_type": string;
    };
    "CapabilityStatus": "AVAILABLE" | "DISABLED" | "UNAVAILABLE";
    "ComponentResponse": {
      "component_type"?: string | null;
      "display_name"?: string | null;
      "id": string;
      "machine_id": string;
      "manufacturer"?: string | null;
      "model"?: string | null;
    };
    "ContextDimensionInput": {
      "freshness_basis": string;
      "quality": components["schemas"]["ContextQuality"];
      "value": components["schemas"]["JsonValue"] | null;
    };
    "ContextQuality": "KNOWN" | "UNKNOWN" | "STALE";
    "ContextSnapshotInput": {
      "environment": components["schemas"]["ContextDimensionInput"];
      "location": components["schemas"]["ContextDimensionInput"];
      "machine_operating_state": components["schemas"]["ContextDimensionInput"];
      "shift": components["schemas"]["ContextDimensionInput"];
      "workload": components["schemas"]["ContextDimensionInput"];
    };
    "ContextSnapshotOutput": {
      "context": components["schemas"]["ContextSnapshotInput"];
      "evidence_id": string;
      "id": string;
    };
    "DeterministicAIFallback": {
      "evidence_bundle_status": components["schemas"]["EvidenceBundleStatus"];
      "exact_history": Array<components["schemas"]["FallbackEvidenceFact"]>;
      "incident_id": string;
      "primary_evidence": Array<components["schemas"]["FallbackEvidenceFact"]>;
      "reason": components["schemas"]["AIAnalysisFallbackReason"];
      "reason_detail": string;
      "semantic_history": components["schemas"]["SemanticEnrichmentSummary"];
      "verification": Array<components["schemas"]["FallbackVerificationFact"]>;
    };
    "DueVerificationEvaluationResponse": {
      "evaluated": Array<components["schemas"]["VerificationRunResponse"]>;
    };
    "EvidenceAttachmentInput": {
      "attachment_type": string;
      "checksum": string;
      "created_at": string;
      "file_size": number;
      "mime_type": string;
      "storage_reference": string;
    };
    "EvidenceAttachmentManifestReference": {
      "attachment_id": string;
      "checksum"?: string | null;
      "file_size"?: number | null;
      "mime_type"?: string | null;
      "storage_reference"?: string | null;
    };
    "EvidenceAttachmentOutput": {
      "attachment_type": string | null;
      "checksum": string | null;
      "created_at": string | null;
      "evidence_id": string;
      "file_size": number | null;
      "id": string;
      "mime_type": string | null;
      "storage_reference": string | null;
    };
    "EvidenceBundleCompleteness": {
      "canonical_readiness_policy": string;
      "incomplete_sections"?: Array<components["schemas"]["EvidenceBundleSection"]>;
      "semantic_retrieval": components["schemas"]["SemanticRetrievalMetadata"];
      "status_reason": string;
      "truncated_sections"?: Array<components["schemas"]["EvidenceBundleSection"]>;
    };
    "EvidenceBundleResponse": {
      "completeness": components["schemas"]["EvidenceBundleCompleteness"];
      "evidence_time_context_snapshots": Array<components["schemas"]["EvidenceTimeContextItem"]>;
      "incident_id": string;
      "primary_incident_evidence": Array<components["schemas"]["BundleEvidenceItem"]>;
      "provenance_index": Array<components["schemas"]["ProvenanceIndexItem"]>;
      "selected_exact_history": Array<components["schemas"]["BundleEvidenceItem"]>;
      "selected_semantic_history": Array<components["schemas"]["BundleEvidenceItem"]>;
      "status": components["schemas"]["EvidenceBundleStatus"];
      "verification_context": Array<components["schemas"]["VerificationContextItem"]>;
    };
    "EvidenceBundleSection": "PRIMARY_INCIDENT_EVIDENCE" | "SELECTED_EXACT_HISTORY" | "SELECTED_SEMANTIC_HISTORY" | "VERIFICATION_CONTEXT" | "EVIDENCE_TIME_CONTEXT_SNAPSHOTS" | "PROVENANCE_INDEX";
    "EvidenceBundleSourceClassification": "PRIMARY_INCIDENT_EVIDENCE" | "EXACT_HISTORY" | "SEMANTIC_HISTORY";
    "EvidenceBundleStatus": "READY" | "PARTIAL" | "INSUFFICIENT_EVIDENCE";
    "EvidenceIngestionResponse": {
      "evidence_id": string;
      "idempotent_replay": boolean;
      "session_id"?: string | null;
    };
    "EvidenceManifest": {
      "entries": Array<components["schemas"]["EvidenceManifestEntry"]>;
      "schema_version": string;
    };
    "EvidenceManifestEntry": {
      "checksum": string;
      "checksum_scope"?: string;
      "component_id"?: string | null;
      "evidence_id": string;
      "incident_id"?: string | null;
      "machine_id": string;
      "original_timestamp": string;
      "provenance_reference": string;
      "session_id": string;
      "source_type": string;
      "storage_references": Array<components["schemas"]["EvidenceAttachmentManifestReference"]>;
    };
    "EvidenceTimeContextItem": {
      "context_snapshots"?: Array<components["schemas"]["ContextSnapshotOutput"]>;
      "evidence_id": string;
      "source_classification": components["schemas"]["EvidenceBundleSourceClassification"];
    };
    "FallbackEvidenceFact": {
      "canonical_event_type": string;
      "canonical_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "component_id": string | null;
      "evidence_id": string;
      "evidence_type": string;
      "machine_id": string;
      "original_timestamp": string;
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "source_classification": components["schemas"]["EvidenceBundleSourceClassification"];
    };
    "FallbackVerificationFact": {
      "completed_at": string | null;
      "evidence_ids"?: Array<string>;
      "result": components["schemas"]["VerificationRunResult"] | null;
      "rule_identifier": string | null;
      "rule_name": string | null;
      "rule_type": components["schemas"]["VerificationRuleType"] | null;
      "started_at": string;
      "verification_run_id": string;
      "window_ends_at": string | null;
    };
    "HTTPValidationError": {
      "detail"?: Array<components["schemas"]["ValidationError"]>;
    };
    "HandoverItemOutput": {
      "due_state": string | null;
      "due_time": string | null;
      "id": string;
      "incident_id": string;
      "owner_ref": string | null;
      "severity": string | null;
      "status": components["schemas"]["IncidentStatus"];
    };
    "HandoverPacketResponse": {
      "acknowledged_at": string | null;
      "created_at": string;
      "id": string;
      "items": Array<components["schemas"]["HandoverItemOutput"]>;
    };
    "HealthResponse": {
      "database"?: "ok";
      "status"?: "ok";
    };
    "HumanObservationInput": {
      "attachments"?: Array<components["schemas"]["EvidenceAttachmentInput"]>;
      "component_id"?: string | null;
      "context_snapshot"?: components["schemas"]["ContextSnapshotInput"] | null;
      "machine_id": string;
      "observation_type": string;
      "original_source_record_id": string;
      "original_timestamp": string;
      "payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "session_id"?: string | null;
    };
    "IncidentAuditAction": "INCIDENT_CREATED" | "EVIDENCE_LINKED" | "EVIDENCE_UNLINKED" | "INCIDENT_SPLIT" | "STATUS_CHANGED" | "OWNER_CHANGED" | "SEVERITY_CHANGED" | "DUE_STATE_CHANGED" | "DUE_TIME_CHANGED" | "RECURRENCE_RECORDED" | "HANDOVER_ACKNOWLEDGED";
    "IncidentAuditOutput": {
      "action": components["schemas"]["IncidentAuditAction"];
      "id": string;
      "occurred_at": string;
      "payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
    };
    "IncidentAuditResponse": {
      "audit_events": Array<components["schemas"]["IncidentAuditOutput"]>;
      "incident_id": string;
    };
    "IncidentCollectionResponse": {
      "items": Array<components["schemas"]["IncidentSummaryResponse"]>;
      "limit": number;
      "offset": number;
      "total": number;
    };
    "IncidentDetailResponse": {
      "audit_events": Array<components["schemas"]["IncidentAuditOutput"]>;
      "created_at": string;
      "due_state": string | null;
      "due_time": string | null;
      "incident_id": string;
      "machine_id": string;
      "owner_ref": string | null;
      "severity": string | null;
      "status": components["schemas"]["IncidentStatus"];
      "updated_at": string;
    };
    "IncidentEvidenceItem": {
      "canonical_event_type": string;
      "canonical_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
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
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_source_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "relationship_type": components["schemas"]["IncidentEvidenceRelationshipType"];
      "source_type": string;
      "unlinked_at": string | null;
    };
    "IncidentEvidenceRelationshipType": "RELATED" | "RECURRENCE" | "VERIFICATION";
    "IncidentEvidenceResponse": {
      "evidence": Array<components["schemas"]["IncidentEvidenceItem"]>;
      "incident_id": string;
    };
    "IncidentStatus": "OPEN" | "VERIFYING" | "VERIFIED" | "RECURRED";
    "IncidentSummaryResponse": {
      "created_at": string;
      "due_state": string | null;
      "due_time": string | null;
      "incident_id": string;
      "machine_id": string;
      "owner_ref": string | null;
      "severity": string | null;
      "status": components["schemas"]["IncidentStatus"];
      "updated_at": string;
    };
    "JsonValue": unknown;
    "LocalOverviewCounts": {
      "components": number;
      "evidence": number;
      "incidents": number;
      "incidents_by_status": {
        [key: string]: number;
      };
    };
    "LocalReturnToServiceSummary": {
      "blocking_reasons": Array<components["schemas"]["ReturnToServiceBlockingReason"]>;
      "policy_identifier": string;
      "policy_revision": number;
      "state": components["schemas"]["ReturnToServiceState"];
    };
    "LocalSyncTransportSummary": {
      "last_acknowledgement"?: string | null;
      "last_error"?: string | null;
      "latest_package_state"?: string | null;
      "transport_available"?: boolean | null;
      "transport_checked_at"?: string | null;
      "transport_configured": boolean;
    };
    "MLAICapabilityReport": {
      "ai_provider": components["schemas"]["OperationalCapability"];
      "embedding_provider": components["schemas"]["OperationalCapability"];
      "qdrant_semantic": components["schemas"]["OperationalCapability"];
      "signals": components["schemas"]["MLAIOperationalSignals"];
    };
    "MLAIOperationalSignals": {
      "ai_citation_rejections": number;
      "ai_claim_policy_rejections": number;
      "ai_provider_errors": number;
      "ai_provider_successes": number;
      "ai_provider_timeouts": number;
      "ai_schema_rejections": number;
      "embedding_provider_failures": number;
      "embedding_provider_successes": number;
      "fallback_reasons": {
        [key: string]: number;
      };
      "indexing_failures": number;
      "last_qdrant_search_latency_ms"?: number | null;
      "qdrant_connectivity_failures": number;
      "qdrant_search_count": number;
      "qdrant_search_failures": number;
      "stale_qdrant_reference_count": number;
    };
    "MachineCollectionResponse": {
      "items": Array<components["schemas"]["MachineResponse"]>;
      "limit": number;
      "offset": number;
      "total": number;
    };
    "MachineComponentsResponse": {
      "components": Array<components["schemas"]["ComponentResponse"]>;
      "machine_id": string;
    };
    "MachineEventInput": {
      "attachments"?: Array<components["schemas"]["EvidenceAttachmentInput"]>;
      "component_id"?: string | null;
      "context_snapshot"?: components["schemas"]["ContextSnapshotInput"] | null;
      "event_type": string;
      "machine_id": string;
      "original_source_record_id": string;
      "original_timestamp": string;
      "payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "session_id"?: string | null;
    };
    "MachineResponse": {
      "asset_code"?: string | null;
      "display_name"?: string | null;
      "id": string;
      "machine_type"?: string | null;
      "manufacturer"?: string | null;
      "model"?: string | null;
      "site_area"?: string | null;
      "site_name"?: string | null;
    };
    "MachineSessionReport": {
      "checksum": string;
      "evidence_manifest": components["schemas"]["EvidenceManifest"];
      "generated_at": string;
      "incident_summaries": Array<components["schemas"]["SessionIncidentSummary"]>;
      "machine_id": string;
      "maintenance_actions": Array<components["schemas"]["SessionMaintenanceAction"]>;
      "operating_summary": components["schemas"]["SessionOperatingSummary"];
      "report_id": string;
      "schema_version": string;
      "session_id": string;
      "sync_metadata": components["schemas"]["SessionReportSyncMetadata"];
      "unresolved_work": Array<components["schemas"]["SessionUnresolvedWork"]>;
      "verification_results": Array<components["schemas"]["SessionVerificationResult"]>;
    };
    "MachineTimelineResponse": {
      "component_id"?: string | null;
      "evidence": Array<components["schemas"]["TimelineEvidenceItem"]>;
      "from_timestamp"?: string | null;
      "machine_id": string;
      "to_timestamp"?: string | null;
    };
    "MaintenanceRecordInput": {
      "attachments"?: Array<components["schemas"]["EvidenceAttachmentInput"]>;
      "component_id"?: string | null;
      "context_snapshot"?: components["schemas"]["ContextSnapshotInput"] | null;
      "machine_id": string;
      "original_source_record_id": string;
      "original_timestamp": string;
      "payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "record_type": string;
      "session_id"?: string | null;
    };
    "MoveEvidenceRequest": {
      "reason": string;
      "target_incident_id": string;
    };
    "MoveEvidenceResponse": {
      "evidence_id": string;
      "new_link_id": string;
      "old_link_id": string;
      "source_incident_id": string;
      "target_incident_id": string;
    };
    "OperatingSessionCloseRequest": {
      "ended_at": string;
      "operating_hours"?: number | null;
    };
    "OperatingSessionOpenRequest": {
      "started_at": string;
    };
    "OperatingSessionResponse": {
      "created_at": string;
      "ended_at": string | null;
      "machine_id": string;
      "operating_hours": number | null;
      "revision": number;
      "session_id": string;
      "started_at": string;
      "state": components["schemas"]["OperatingSessionState"];
      "updated_at": string;
    };
    "OperatingSessionRolloverRequest": {
      "ended_at": string;
      "new_started_at": string;
      "operating_hours"?: number | null;
    };
    "OperatingSessionRolloverResponse": {
      "closed_session": components["schemas"]["OperatingSessionResponse"];
      "new_session": components["schemas"]["OperatingSessionResponse"];
    };
    "OperatingSessionState": "OPEN" | "CLOSED";
    "OperationalCapability": {
      "model"?: string | null;
      "provider"?: string | null;
      "reason"?: string | null;
      "status": components["schemas"]["CapabilityStatus"];
      "verified_at"?: string | null;
    };
    "OverviewResponse": {
      "active_session"?: components["schemas"]["OperatingSessionResponse"] | null;
      "counts": components["schemas"]["LocalOverviewCounts"];
      "demo_mode"?: boolean;
      "machine": components["schemas"]["MachineResponse"];
      "operating_state"?: components["schemas"]["OperatingSessionState"] | null;
      "return_to_service": components["schemas"]["LocalReturnToServiceSummary"];
      "sync": components["schemas"]["LocalSyncTransportSummary"];
      "unresolved_incident_count": number;
    };
    "ProvenanceIndexItem": {
      "evidence_id": string;
      "original_source_record_id": string;
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "source_classification": components["schemas"]["EvidenceBundleSourceClassification"];
      "source_type": string;
    };
    "ReturnToServiceBlockingReason": {
      "code": string;
      "evidence_ids"?: Array<string>;
      "incident_id"?: string | null;
      "message": string;
      "verification_id"?: string | null;
    };
    "ReturnToServiceResponse": {
      "blocking_reasons"?: Array<components["schemas"]["ReturnToServiceBlockingReason"]>;
      "evidence_ids"?: Array<string>;
      "incident_ids"?: Array<string>;
      "policy_identifier": string;
      "policy_revision": number;
      "state": components["schemas"]["ReturnToServiceState"];
      "verification_ids"?: Array<string>;
    };
    "ReturnToServiceState": "CLEARED" | "VERIFICATION_REQUIRED" | "DO_NOT_RETURN";
    "SemanticEnrichmentState": "AVAILABLE" | "DISABLED" | "UNAVAILABLE";
    "SemanticEnrichmentSummary": {
      "attempted": boolean;
      "configured": boolean;
      "failure_reasons"?: Array<string>;
      "selected_match_count": number;
      "state": components["schemas"]["SemanticEnrichmentState"];
    };
    "SemanticHistoryFailure": "SEMANTIC_SEARCH_DISABLED" | "EMBEDDING_UNAVAILABLE" | "SEMANTIC_INDEX_UNAVAILABLE";
    "SemanticRetrievalMetadata": {
      "attempted": boolean;
      "configured": boolean;
      "failed": boolean;
      "failures"?: Array<components["schemas"]["SemanticHistoryFailure"]>;
      "queried_primary_evidence_ids"?: Array<string>;
    };
    "SemanticSearchFailure": "SEMANTIC_SEARCH_DISABLED" | "EMBEDDING_UNAVAILABLE" | "SEMANTIC_INDEX_UNAVAILABLE" | "DIMENSION_MISMATCH" | "SEMANTIC_INDEX_INCOMPATIBLE";
    "SemanticSearchRequest": {
      "component_id"?: string | null;
      "limit"?: number;
      "query": string;
    };
    "SemanticSearchResponse": {
      "available": boolean;
      "classification"?: "Semantic";
      "failure"?: components["schemas"]["SemanticSearchFailure"] | null;
      "reason"?: string | null;
      "results"?: Array<components["schemas"]["SemanticSearchResult"]>;
    };
    "SemanticSearchResult": {
      "canonical_event_type": string;
      "canonical_payload": {
        [key: string]: unknown;
      };
      "classification"?: "Semantic";
      "component_id": string | null;
      "evidence_id": string;
      "incident_id": string | null;
      "machine_id": string;
      "original_timestamp": string;
      "provenance": {
        [key: string]: unknown;
      };
      "session_id": string | null;
      "similarity_score": number;
      "source_type": string;
    };
    "SessionIncidentSummary": {
      "component_id"?: string | null;
      "first_seen"?: string | null;
      "incident_id": string;
      "last_seen"?: string | null;
      "occurrence_count": number;
      "severity"?: string | null;
      "state": components["schemas"]["IncidentStatus"];
    };
    "SessionMaintenanceAction": {
      "action_type": string;
      "canonical_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "component_id"?: string | null;
      "evidence_id": string;
      "original_timestamp": string;
    };
    "SessionOperatingSummary": {
      "end": string;
      "operating_hours"?: number | null;
      "session_state": components["schemas"]["OperatingSessionState"];
      "start": string;
    };
    "SessionReportAcknowledgementState": "NOT_ACKNOWLEDGED";
    "SessionReportSyncMetadata": {
      "acknowledgement_state": components["schemas"]["SessionReportAcknowledgementState"];
      "local_revision": number;
      "report_revision": number;
    };
    "SessionUnresolvedWork": {
      "component_id"?: string | null;
      "incident_id": string;
      "state": components["schemas"]["IncidentStatus"];
    };
    "SessionVerificationResult": {
      "completed_at"?: string | null;
      "evidence_event_ids": Array<string>;
      "incident_id": string;
      "result"?: components["schemas"]["VerificationRunResult"] | null;
      "rule_identifier"?: string | null;
      "started_at": string;
      "verification_run_id": string;
      "window_ends_at"?: string | null;
    };
    "SplitIncidentRequest": {
      "evidence_ids": Array<string>;
      "reason": string;
    };
    "SplitIncidentResponse": {
      "evidence_ids": Array<string>;
      "new_incident_id": string;
      "new_link_ids": Array<string>;
      "old_link_ids": Array<string>;
      "source_incident_id": string;
    };
    "SyncConflictSummary": {
      "central_revision": number;
      "conflict_id": string;
      "detected_at": string;
      "local_revision": number;
      "object_id"?: string | null;
      "package_id": string;
      "resolution_metadata": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "state": string;
    };
    "SyncLatestPackageStatus": {
      "attempt_count": number;
      "local_revision": number;
      "package_id": string;
      "report_revision": number;
      "session_id": string;
      "state": string;
    };
    "SyncStatusResponse": {
      "conflict_count": number;
      "conflicts": Array<components["schemas"]["SyncConflictSummary"]>;
      "failed_item_count": number;
      "last_acknowledgement"?: string | null;
      "last_error"?: string | null;
      "last_transmission_attempt"?: string | null;
      "latest_package"?: components["schemas"]["SyncLatestPackageStatus"] | null;
      "machine_id": string;
      "pending_item_count": number;
      "transport_available"?: boolean | null;
      "transport_checked_at"?: string | null;
      "transport_configured": boolean;
    };
    "TimelineEvidenceItem": {
      "attachments": Array<components["schemas"]["EvidenceAttachmentOutput"]>;
      "canonical_event_type": string;
      "canonical_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "component_id": string | null;
      "context_snapshots": Array<components["schemas"]["ContextSnapshotOutput"]>;
      "evidence_id": string;
      "ingestion_timestamp": string;
      "machine_id": string;
      "original_source_record_id": string;
      "original_timestamp": string;
      "provenance": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "raw_source_payload": {
        [key: string]: components["schemas"]["JsonValue"];
      };
      "source_type": string;
    };
    "ValidatedAIAnalysis": {
      "claims": Array<components["schemas"]["AIClaim"]>;
      "limitations": Array<string>;
      "status"?: "VALIDATED";
      "summary": string;
    };
    "ValidationError": {
      "ctx"?: Record<string, never>;
      "input"?: unknown;
      "loc": Array<string | number>;
      "msg": string;
      "type": string;
    };
    "VerificationContextItem": {
      "completed_at": string | null;
      "evidence_ids"?: Array<string>;
      "result": components["schemas"]["VerificationRunResult"] | null;
      "rule_identifier": string | null;
      "rule_name": string | null;
      "rule_type": components["schemas"]["VerificationRuleType"] | null;
      "started_at": string;
      "verification_rule_id": string;
      "verification_run_id": string;
      "window_ends_at": string | null;
      "window_minutes": number | null;
    };
    "VerificationRuleType": "NO_EVENT";
    "VerificationRunResponse": {
      "completed_at": string | null;
      "evidence_event_ids": Array<string>;
      "id": string;
      "incident_id": string;
      "result": components["schemas"]["VerificationRunResult"] | null;
      "rule_identifier": string;
      "rule_name": string;
      "rule_type": components["schemas"]["VerificationRuleType"];
      "started_at": string;
      "verification_rule_id": string;
      "window_ends_at": string;
      "window_minutes": number;
    };
    "VerificationRunResult": "SUCCEEDED" | "RECURRENCE_DETECTED";
    "VerificationRunsResponse": {
      "incident_id": string;
      "runs": Array<components["schemas"]["VerificationRunResponse"]>;
    };
  };
}
