"""Add durable post-commit semantic indexing outbox.

Revision ID: 0002_semantic_index_outbox
Revises: 0001_global_initial
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_semantic_index_outbox"
down_revision = "0001_global_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_index_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_report_revision", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id", name="uq_semantic_index_outbox_evidence"),
    )
    op.create_index(
        "ix_semantic_index_outbox_status_created",
        "semantic_index_outbox",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_index_outbox_status_created", table_name="semantic_index_outbox")
    op.drop_table("semantic_index_outbox")
