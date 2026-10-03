"""durable synchronization outbox and conflicts

Revision ID: b72d6e31c9f0
Revises: f17c5d2e8a44
Create Date: 2026-10-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b72d6e31c9f0"
down_revision: Union[str, None] = "f17c5d2e8a44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The predecessor tables were intentionally empty placeholder records with
    # no package/revision semantics. Replace them with the durable protocol.
    op.drop_table("sync_changes")
    op.drop_table("sync_conflicts")

    op.create_table(
        "sync_outbox_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("local_revision", sa.Integer(), nullable=False),
        sa.Column("report_revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "PENDING",
                "SENDING",
                "ACKNOWLEDGED",
                "FAILED",
                "CONFLICT",
                name="sync_outbox_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("central_revision", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("transport_available", sa.Boolean(), nullable=True),
        sa.Column("transport_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"], ["machines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operating_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["machine_session_reports.report_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id", "local_revision", name="uq_sync_outbox_package_revision"
        ),
    )
    op.create_index(
        "ix_sync_outbox_machine_state",
        "sync_outbox_items",
        ["machine_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_sync_outbox_machine_created",
        "sync_outbox_items",
        ["machine_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "sync_conflicts",
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("local_revision", sa.Integer(), nullable=False),
        sa.Column("central_revision", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "OPEN",
                "RESOLVED",
                name="sync_conflict_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("resolution_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["machine_id"], ["machines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operating_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("conflict_id"),
        sa.UniqueConstraint(
            "package_id",
            "local_revision",
            "central_revision",
            name="uq_sync_conflict_package_revisions",
        ),
    )
    op.create_index(
        "ix_sync_conflicts_machine_detected",
        "sync_conflicts",
        ["machine_id", "detected_at", "conflict_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sync_conflicts_machine_detected", table_name="sync_conflicts")
    op.drop_table("sync_conflicts")
    op.drop_index("ix_sync_outbox_machine_created", table_name="sync_outbox_items")
    op.drop_index("ix_sync_outbox_machine_state", table_name="sync_outbox_items")
    op.drop_table("sync_outbox_items")

    op.create_table(
        "sync_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
