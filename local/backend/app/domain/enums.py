from enum import StrEnum


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    RECURRED = "RECURRED"


class ContextQuality(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class EvidenceBundleStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceBundleSourceClassification(StrEnum):
    PRIMARY_INCIDENT_EVIDENCE = "PRIMARY_INCIDENT_EVIDENCE"
    EXACT_HISTORY = "EXACT_HISTORY"
    SEMANTIC_HISTORY = "SEMANTIC_HISTORY"


class EvidenceBundleSection(StrEnum):
    PRIMARY_INCIDENT_EVIDENCE = "PRIMARY_INCIDENT_EVIDENCE"
    SELECTED_EXACT_HISTORY = "SELECTED_EXACT_HISTORY"
    SELECTED_SEMANTIC_HISTORY = "SELECTED_SEMANTIC_HISTORY"
    VERIFICATION_CONTEXT = "VERIFICATION_CONTEXT"
    EVIDENCE_TIME_CONTEXT_SNAPSHOTS = "EVIDENCE_TIME_CONTEXT_SNAPSHOTS"
    PROVENANCE_INDEX = "PROVENANCE_INDEX"


class IncidentEvidenceRelationshipType(StrEnum):
    """Controlled MVP vocabulary for why evidence is attached to an incident.

    RELATED is intentionally broad because the specification does not yet define
    finer evidence roles. RECURRENCE and VERIFICATION are kept explicit because
    they have lifecycle meaning in the MVP requirements.
    """

    RELATED = "RELATED"
    RECURRENCE = "RECURRENCE"
    VERIFICATION = "VERIFICATION"


class IncidentAuditAction(StrEnum):
    INCIDENT_CREATED = "INCIDENT_CREATED"
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    EVIDENCE_UNLINKED = "EVIDENCE_UNLINKED"
    INCIDENT_SPLIT = "INCIDENT_SPLIT"
    STATUS_CHANGED = "STATUS_CHANGED"
    OWNER_CHANGED = "OWNER_CHANGED"
    SEVERITY_CHANGED = "SEVERITY_CHANGED"
    DUE_STATE_CHANGED = "DUE_STATE_CHANGED"
    DUE_TIME_CHANGED = "DUE_TIME_CHANGED"
    RECURRENCE_RECORDED = "RECURRENCE_RECORDED"
    HANDOVER_ACKNOWLEDGED = "HANDOVER_ACKNOWLEDGED"


class VerificationRuleType(StrEnum):
    NO_EVENT = "NO_EVENT"


class VerificationRunResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    RECURRENCE_DETECTED = "RECURRENCE_DETECTED"


class EvidenceSourceType(StrEnum):
    MACHINE_EVENT = "MACHINE_EVENT"
    MAINTENANCE_RECORD = "MAINTENANCE_RECORD"
    HUMAN_OBSERVATION = "HUMAN_OBSERVATION"


class OperatingSessionState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SessionReportAcknowledgementState(StrEnum):
    NOT_ACKNOWLEDGED = "NOT_ACKNOWLEDGED"


class SyncOutboxState(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"


class SyncConflictState(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ReturnToServiceState(StrEnum):
    CLEARED = "CLEARED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    DO_NOT_RETURN = "DO_NOT_RETURN"
