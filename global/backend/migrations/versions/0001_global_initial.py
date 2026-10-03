"""Initial canonical global PostgreSQL fleet schema.

Revision ID: 0001_global_initial
Revises: None
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_global_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('machines',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('asset_code', sa.String(length=128), nullable=True),
    sa.Column('machine_type', sa.String(length=128), nullable=True),
    sa.Column('manufacturer', sa.String(length=255), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('site_name', sa.String(length=255), nullable=True),
    sa.Column('site_area', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_machines')),
    sa.UniqueConstraint('asset_code', name='uq_machines_asset_code')
    )
    op.create_table('verification_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('identifier', sa.String(length=255), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('rule_type', sa.Enum('NO_EVENT', name='verification_rule_type', native_enum=False, create_constraint=True), nullable=True),
    sa.Column('window_minutes', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_rules')),
    sa.UniqueConstraint('identifier', name='uq_verification_rules_identifier')
    )
    op.create_table('components',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('component_type', sa.String(length=128), nullable=True),
    sa.Column('manufacturer', sa.String(length=255), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name=op.f('fk_components_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_components')),
    sa.UniqueConstraint('id', 'machine_id', name='uq_components_id_machine_id')
    )
    op.create_index('ix_components_machine_id', 'components', ['machine_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('state', sa.String(length=64), nullable=False),
    sa.Column('operating_hours', sa.Float(), nullable=True),
    sa.Column('latest_report_revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name=op.f('fk_sessions_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index('ix_sessions_machine_report_revision', 'sessions', ['machine_id', 'latest_report_revision'], unique=False)
    op.create_index('ix_sessions_machine_started', 'sessions', ['machine_id', 'started_at'], unique=False)
    op.create_table('evidence_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('source_machine_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('component_id', sa.Uuid(), nullable=True),
    sa.Column('source_type', sa.String(length=100), nullable=False),
    sa.Column('original_source_record_id', sa.String(length=255), nullable=True),
    sa.Column('original_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ingestion_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('canonical_event_type', sa.String(length=100), nullable=False),
    sa.Column('canonical_payload', sa.JSON(), nullable=False),
    sa.Column('raw_source_payload', sa.JSON(), nullable=False),
    sa.Column('provenance', sa.JSON(), nullable=False),
    sa.Column('checksum', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['component_id', 'machine_id'], ['components.id', 'components.machine_id'], name='fk_evidence_events_component_machine', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name=op.f('fk_evidence_events_machine_id_machines'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_evidence_events_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_machine_id'], ['machines.id'], name=op.f('fk_evidence_events_source_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_events')),
    sa.UniqueConstraint('source_machine_id', 'source_type', 'original_source_record_id', name='uq_evidence_source_identity')
    )
    op.create_index('ix_evidence_events_component_timeline', 'evidence_events', ['component_id', 'original_timestamp', 'id'], unique=False)
    op.create_index('ix_evidence_events_ingestion_timestamp', 'evidence_events', ['ingestion_timestamp'], unique=False)
    op.create_index('ix_evidence_events_machine_timeline', 'evidence_events', ['machine_id', 'original_timestamp', 'id'], unique=False)
    op.create_index('ix_evidence_events_session_timeline', 'evidence_events', ['session_id', 'original_timestamp', 'id'], unique=False)
    op.create_table('incidents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('component_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('OPEN', 'VERIFYING', 'VERIFIED', 'RECURRED', name='incident_status', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('owner_ref', sa.String(length=255), nullable=True),
    sa.Column('severity', sa.String(length=64), nullable=True),
    sa.Column('due_state', sa.String(length=64), nullable=True),
    sa.Column('due_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['component_id'], ['components.id'], name=op.f('fk_incidents_component_id_components'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name=op.f('fk_incidents_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents'))
    )
    op.create_index('ix_incidents_component_status', 'incidents', ['component_id', 'status'], unique=False)
    op.create_index('ix_incidents_last_seen', 'incidents', ['last_seen_at'], unique=False)
    op.create_index('ix_incidents_machine_status', 'incidents', ['machine_id', 'status'], unique=False)
    op.create_table('session_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('source_machine_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('schema_version', sa.String(length=64), nullable=False),
    sa.Column('report_revision', sa.Integer(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('checksum', sa.String(length=255), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_reports_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_machine_id'], ['machines.id'], name=op.f('fk_session_reports_source_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_reports')),
    sa.UniqueConstraint('report_id', name='uq_session_reports_report_id'),
    sa.UniqueConstraint('source_machine_id', 'session_id', 'report_revision', name='uq_session_report_revision')
    )
    op.create_index('ix_session_reports_session_revision', 'session_reports', ['session_id', 'report_revision'], unique=False)
    op.create_table('sync_receipts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('package_id', sa.Uuid(), nullable=False),
    sa.Column('source_machine_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('report_revision', sa.Integer(), nullable=False),
    sa.Column('schema_version', sa.String(length=64), nullable=False),
    sa.Column('checksum', sa.String(length=255), nullable=False),
    sa.Column('acknowledgement_status', sa.String(length=64), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_sync_receipts_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_machine_id'], ['machines.id'], name=op.f('fk_sync_receipts_source_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_receipts')),
    sa.UniqueConstraint('source_machine_id', 'package_id', 'report_revision', name='uq_sync_receipt_package_revision')
    )
    op.create_index('ix_sync_receipts_machine_session', 'sync_receipts', ['source_machine_id', 'session_id', 'received_at'], unique=False)
    op.create_table('context_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('evidence_event_id', sa.Uuid(), nullable=False),
    sa.Column('quality', sa.Enum('KNOWN', 'UNKNOWN', 'STALE', name='context_quality', native_enum=False, create_constraint=True), nullable=True),
    sa.Column('snapshot_payload', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['evidence_event_id'], ['evidence_events.id'], name=op.f('fk_context_snapshots_evidence_event_id_evidence_events'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_snapshots'))
    )
    op.create_index('ix_context_snapshots_evidence_event_id', 'context_snapshots', ['evidence_event_id'], unique=False)
    op.create_table('evidence_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('evidence_event_id', sa.Uuid(), nullable=False),
    sa.Column('attachment_type', sa.String(length=100), nullable=True),
    sa.Column('storage_reference', sa.String(length=1024), nullable=True),
    sa.Column('mime_type', sa.String(length=255), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('checksum', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('file_size IS NULL OR file_size >= 0', name=op.f('ck_evidence_attachments_file_size_nonnegative')),
    sa.ForeignKeyConstraint(['evidence_event_id'], ['evidence_events.id'], name=op.f('fk_evidence_attachments_evidence_event_id_evidence_events'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_attachments'))
    )
    op.create_index('ix_evidence_attachments_evidence_event_id', 'evidence_attachments', ['evidence_event_id'], unique=False)
    op.create_table('incident_audit_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.Enum('INCIDENT_CREATED', 'EVIDENCE_LINKED', 'EVIDENCE_UNLINKED', 'INCIDENT_SPLIT', 'STATUS_CHANGED', 'OWNER_CHANGED', 'SEVERITY_CHANGED', 'DUE_STATE_CHANGED', 'DUE_TIME_CHANGED', 'RECURRENCE_RECORDED', 'HANDOVER_ACKNOWLEDGED', name='incident_audit_action', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_audit_events_incident_id_incidents'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_audit_events'))
    )
    op.create_index('ix_incident_audit_events_incident_timeline', 'incident_audit_events', ['incident_id', 'occurred_at', 'id'], unique=False)
    op.create_table('incident_evidence_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('evidence_event_id', sa.Uuid(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('relationship_type', sa.Enum('RELATED', 'RECURRENCE', 'VERIFICATION', name='incident_evidence_relationship_type', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('deterministic_rule_identifier', sa.String(length=255), nullable=True),
    sa.Column('link_reason', sa.Text(), nullable=False),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('unlinked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('(is_active AND unlinked_at IS NULL) OR ((NOT is_active) AND unlinked_at IS NOT NULL)', name=op.f('ck_incident_evidence_links_active_unlinked_timestamp_consistent')),
    sa.ForeignKeyConstraint(['evidence_event_id'], ['evidence_events.id'], name=op.f('fk_incident_evidence_links_evidence_event_id_evidence_events'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_evidence_links_incident_id_incidents'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_evidence_links'))
    )
    op.create_index('ix_incident_evidence_links_active_incident', 'incident_evidence_links', ['incident_id', 'evidence_event_id'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_index('ix_incident_evidence_links_evidence_retrieval', 'incident_evidence_links', ['evidence_event_id', 'linked_at'], unique=False)
    op.create_index('ix_incident_evidence_links_incident_retrieval', 'incident_evidence_links', ['incident_id', 'linked_at'], unique=False)
    op.create_table('incident_session_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_session_links_incident_id_incidents'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_incident_session_links_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_session_links')),
    sa.UniqueConstraint('incident_id', 'session_id', name='uq_incident_session_link')
    )
    op.create_index('ix_incident_session_links_session', 'incident_session_links', ['session_id', 'incident_id'], unique=False)
    op.create_table('maintenance_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('component_id', sa.Uuid(), nullable=True),
    sa.Column('action_type', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('original_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ingestion_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('provenance', sa.JSON(), server_default='{}', nullable=False),
    sa.ForeignKeyConstraint(['component_id'], ['components.id'], name=op.f('fk_maintenance_actions_component_id_components'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_maintenance_actions_incident_id_incidents'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], name=op.f('fk_maintenance_actions_machine_id_machines'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_maintenance_actions_session_id_sessions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_maintenance_actions'))
    )
    op.create_index('ix_maintenance_actions_incident_time', 'maintenance_actions', ['incident_id', 'original_timestamp'], unique=False)
    op.create_index('ix_maintenance_actions_machine_time', 'maintenance_actions', ['machine_id', 'original_timestamp'], unique=False)
    op.create_table('sync_conflicts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_machine_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('incoming_package_id', sa.Uuid(), nullable=False),
    sa.Column('existing_receipt_id', sa.Uuid(), nullable=True),
    sa.Column('conflict_type', sa.String(length=64), nullable=False),
    sa.Column('incoming_report_revision', sa.Integer(), nullable=False),
    sa.Column('existing_report_revision', sa.Integer(), nullable=True),
    sa.Column('incoming_checksum', sa.String(length=255), nullable=True),
    sa.Column('existing_checksum', sa.String(length=255), nullable=True),
    sa.Column('incoming_metadata', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('existing_metadata', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolution_status', sa.String(length=64), server_default='UNRESOLVED', nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution_notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['existing_receipt_id'], ['sync_receipts.id'], name=op.f('fk_sync_conflicts_existing_receipt_id_sync_receipts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_sync_conflicts_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_machine_id'], ['machines.id'], name=op.f('fk_sync_conflicts_source_machine_id_machines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_conflicts'))
    )
    op.create_index('ix_sync_conflicts_machine_session', 'sync_conflicts', ['source_machine_id', 'session_id', 'detected_at'], unique=False)
    op.create_table('verification_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('source_machine_id', sa.Uuid(), nullable=False),
    sa.Column('verification_rule_id', sa.Uuid(), nullable=True),
    sa.Column('rule_identifier', sa.String(length=255), nullable=True),
    sa.Column('result', sa.Enum('SUCCEEDED', 'RECURRENCE_DETECTED', name='verification_run_result', native_enum=False, create_constraint=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('original_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ingestion_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_report_revision', sa.Integer(), nullable=True),
    sa.Column('outcome_payload', sa.JSON(), server_default='{}', nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_verification_runs_incident_id_incidents'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_verification_runs_session_id_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_machine_id'], ['machines.id'], name=op.f('fk_verification_runs_source_machine_id_machines'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['verification_rule_id'], ['verification_rules.id'], name=op.f('fk_verification_runs_verification_rule_id_verification_rules'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_runs'))
    )
    op.create_index('ix_verification_runs_incident_lookup', 'verification_runs', ['incident_id', 'started_at'], unique=False)
    op.create_index('ix_verification_runs_session_lookup', 'verification_runs', ['session_id', 'started_at'], unique=False)
    op.create_table('verification_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('verification_run_id', sa.Uuid(), nullable=False),
    sa.Column('evidence_event_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['evidence_event_id'], ['evidence_events.id'], name=op.f('fk_verification_evidence_evidence_event_id_evidence_events'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['verification_run_id'], ['verification_runs.id'], name=op.f('fk_verification_evidence_verification_run_id_verification_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_evidence')),
    sa.UniqueConstraint('verification_run_id', 'evidence_event_id', name='uq_verification_evidence_run_evidence')
    )
    op.create_index('ix_verification_evidence_evidence_event_id', 'verification_evidence', ['evidence_event_id'], unique=False)
    op.create_index('ix_verification_evidence_run_id', 'verification_evidence', ['verification_run_id'], unique=False)


def downgrade() -> None:
    op.drop_table('verification_evidence')
    op.drop_table('verification_runs')
    op.drop_table('sync_conflicts')
    op.drop_table('maintenance_actions')
    op.drop_table('incident_session_links')
    op.drop_table('incident_evidence_links')
    op.drop_table('incident_audit_events')
    op.drop_table('evidence_attachments')
    op.drop_table('context_snapshots')
    op.drop_table('sync_receipts')
    op.drop_table('session_reports')
    op.drop_table('incidents')
    op.drop_table('evidence_events')
    op.drop_table('sessions')
    op.drop_table('components')
    op.drop_table('verification_rules')
    op.drop_table('machines')
