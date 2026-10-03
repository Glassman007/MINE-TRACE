"""historical context and attachment metadata

Revision ID: 7c91a2e4f6b8
Revises: 4ab3b3b323b6
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "7c91a2e4f6b8"
down_revision: str | None = "4ab3b3b323b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New writes use field-level quality inside the immutable fixed-dimension
    # snapshot payload. The former aggregate quality remains for compatibility
    # with already-persisted snapshots, but is nullable for new records.
    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.alter_column(
            "quality",
            existing_type=sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "STALE",
                name="context_quality",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        )

    # Columns are nullable at the database layer only so an upgraded database
    # with legacy attachment identity rows does not receive fabricated metadata.
    # Current application input requires all metadata fields for new writes.
    with op.batch_alter_table("evidence_attachments") as batch_op:
        batch_op.add_column(sa.Column("attachment_type", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("storage_reference", sa.String(length=1024), nullable=True))
        batch_op.add_column(sa.Column("mime_type", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("file_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("checksum", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "file_size_nonnegative",
            "file_size IS NULL OR file_size >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_attachments") as batch_op:
        batch_op.drop_constraint(
            "ck_evidence_attachments_file_size_nonnegative", type_="check"
        )
        batch_op.drop_column("created_at")
        batch_op.drop_column("checksum")
        batch_op.drop_column("file_size")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("storage_reference")
        batch_op.drop_column("attachment_type")

    # Downgrade cannot safely restore NOT NULL if new-format snapshots with NULL
    # aggregate quality exist. Fail rather than invent an aggregate quality.
    connection = op.get_bind()
    null_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM context_snapshots WHERE quality IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            "cannot downgrade: context snapshots exist without legacy aggregate quality"
        )

    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.alter_column(
            "quality",
            existing_type=sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "STALE",
                name="context_quality",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        )
