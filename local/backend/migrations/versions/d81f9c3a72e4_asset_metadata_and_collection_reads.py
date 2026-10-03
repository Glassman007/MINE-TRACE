"""asset metadata and collection reads

Revision ID: d81f9c3a72e4
Revises: c6f3e92a4d11
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d81f9c3a72e4"
down_revision: str | None = "c6f3e92a4d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All metadata is nullable so existing authoritative asset identities migrate
    # without inventing historical/operational presentation data.
    with op.batch_alter_table("machines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("asset_code", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("machine_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("manufacturer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("site_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("site_area", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint("uq_machines_asset_code", ["asset_code"])

    with op.batch_alter_table("components", schema=None) as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("component_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("manufacturer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("components", schema=None) as batch_op:
        batch_op.drop_column("model")
        batch_op.drop_column("manufacturer")
        batch_op.drop_column("component_type")
        batch_op.drop_column("display_name")

    with op.batch_alter_table("machines", schema=None) as batch_op:
        batch_op.drop_constraint("uq_machines_asset_code", type_="unique")
        batch_op.drop_column("site_area")
        batch_op.drop_column("site_name")
        batch_op.drop_column("model")
        batch_op.drop_column("manufacturer")
        batch_op.drop_column("machine_type")
        batch_op.drop_column("asset_code")
        batch_op.drop_column("display_name")
