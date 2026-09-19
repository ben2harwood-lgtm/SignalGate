"""Tenant-scoped feed policy.

Revision ID: 20260919_0006
Revises: 20260919_0005
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0006"
down_revision = "20260919_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feeds", sa.Column("allowed_symbols_json", sa.Text(), nullable=True))
    op.add_column("feeds", sa.Column("expiry_minutes", sa.Integer(), nullable=True))
    op.add_column("feeds", sa.Column("default_lot_size", sa.Float(), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE feeds SET expiry_minutes = 5, default_lot_size = 0.01 "
            "WHERE expiry_minutes IS NULL OR default_lot_size IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("feeds", "default_lot_size")
    op.drop_column("feeds", "expiry_minutes")
    op.drop_column("feeds", "allowed_symbols_json")
