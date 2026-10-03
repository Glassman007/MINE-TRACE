"""immutable deterministic machine session reports

Revision ID: f17c5d2e8a44
Revises: e92f4a1b7c10
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "f17c5d2e8a44"
down_revision: str | None = "e92f4a1b7c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "machine_session_reports",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_revision", sa.Integer(), nullable=False),
        sa.Column("report_revision", sa.Integer(), nullable=False),
        sa.Column(
            "acknowledgement_state",
            sa.Enum(
                "NOT_ACKNOWLEDGED",
                name="session_report_ack_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operating_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("report_id"),
        sa.UniqueConstraint("session_id", "report_revision", name="uq_session_report_revision"),
    )
    op.create_index(
        "ix_machine_session_reports_machine_session",
        "machine_session_reports",
        ["machine_id", "session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_machine_session_reports_machine_session",
        table_name="machine_session_reports",
    )
    op.drop_table("machine_session_reports")
