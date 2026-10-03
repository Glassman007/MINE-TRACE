"""handover snapshot persistence

Revision ID: c6f3e92a4d11
Revises: a4d091e00ba9
Create Date: 2026-10-02 22:40:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c6f3e92a4d11"
down_revision: Union[str, None] = "a4d091e00ba9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable for migration compatibility with handover rows that may predate
    # snapshot semantics. New application writes always populate status and copy
    # every requested snapshot field exactly, including legitimate NULL values.
    with op.batch_alter_table("handover_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("severity_snapshot", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("owner_ref_snapshot", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "status_snapshot",
                sa.Enum(
                    "OPEN",
                    "VERIFYING",
                    "VERIFIED",
                    "RECURRED",
                    name="handover_item_incident_status",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("due_state_snapshot", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("due_time_snapshot", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("handover_items", schema=None) as batch_op:
        batch_op.drop_column("due_time_snapshot")
        batch_op.drop_column("due_state_snapshot")
        batch_op.drop_column("status_snapshot")
        batch_op.drop_column("owner_ref_snapshot")
        batch_op.drop_column("severity_snapshot")
