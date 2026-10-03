"""persistent operating sessions and nullable evidence relationship

Revision ID: e92f4a1b7c10
Revises: d81f9c3a72e4
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e92f4a1b7c10"
down_revision: str | None = "d81f9c3a72e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operating_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "OPEN",
                "CLOSED",
                name="operating_session_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("operating_hours", sa.Float(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="operating_session_revision_positive"),
        sa.CheckConstraint(
            "operating_hours IS NULL OR operating_hours >= 0",
            name="operating_session_operating_hours_nonnegative",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="operating_session_end_not_before_start",
        ),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_operating_sessions_machine_started",
        "operating_sessions",
        ["machine_id", "started_at", "session_id"],
        unique=False,
    )
    op.create_index(
        "uq_operating_sessions_one_open_per_machine",
        "operating_sessions",
        ["machine_id"],
        unique=True,
        sqlite_where=sa.text("state = 'OPEN'"),
    )

    # Existing evidence deliberately remains NULL. No timestamp-based historical
    # session inference is performed by this migration.
    with op.batch_alter_table("evidence_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_events_session",
            "operating_sessions",
            ["session_id"],
            ["session_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_evidence_events_session_id", ["session_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("evidence_events", schema=None) as batch_op:
        batch_op.drop_index("ix_evidence_events_session_id")
        batch_op.drop_constraint("fk_evidence_events_session", type_="foreignkey")
        batch_op.drop_column("session_id")

    op.drop_index("uq_operating_sessions_one_open_per_machine", table_name="operating_sessions")
    op.drop_index("ix_operating_sessions_machine_started", table_name="operating_sessions")
    op.drop_table("operating_sessions")
