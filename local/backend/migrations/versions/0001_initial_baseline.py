"""initial backend baseline

Revision ID: 0001_initial_baseline
Revises:
Create Date: 2026-10-02
"""

revision = "0001_initial_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No business tables are introduced in the architecture-only baseline.
    pass


def downgrade() -> None:
    pass
