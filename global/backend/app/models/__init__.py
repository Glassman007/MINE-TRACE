"""Canonical global SQLAlchemy records registered with ``Base.metadata``."""

from app.models.evidence import ContextSnapshotRecord, EvidenceAttachmentRecord, EvidenceEventRecord, ImmutableContextSnapshotViolation
from app.models.incidents import AppendOnlyAuditViolation, IncidentAuditEventRecord, IncidentEvidenceLinkRecord, IncidentRecord, IncidentSessionLinkRecord
from app.models.maintenance import MaintenanceActionRecord
from app.models.machines import ComponentRecord, MachineRecord
from app.models.sessions import OperatingSessionRecord
from app.models.semantic_index import SemanticIndexOutboxRecord
from app.models.sync import SessionReportRecord, SyncConflictRecord, SyncReceiptRecord
from app.models.verification import VerificationEvidenceRecord, VerificationRuleRecord, VerificationRunRecord

__all__ = [
    "AppendOnlyAuditViolation",
    "ComponentRecord",
    "ContextSnapshotRecord",
    "EvidenceAttachmentRecord",
    "EvidenceEventRecord",
    "ImmutableContextSnapshotViolation",
    "IncidentAuditEventRecord",
    "IncidentEvidenceLinkRecord",
    "IncidentRecord",
    "IncidentSessionLinkRecord",
    "MachineRecord",
    "MaintenanceActionRecord",
    "OperatingSessionRecord",
    "SemanticIndexOutboxRecord",
    "SessionReportRecord",
    "SyncConflictRecord",
    "SyncReceiptRecord",
    "VerificationEvidenceRecord",
    "VerificationRuleRecord",
    "VerificationRunRecord",
]
