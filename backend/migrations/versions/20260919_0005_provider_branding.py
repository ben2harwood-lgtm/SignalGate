"""Provider Edition branding fields.

Revision ID: 20260919_0005
Revises: 20260919_0004
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0005"
down_revision = "20260919_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("brand_display_name", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("brand_logo_url", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("brand_primary_color", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("support_contact", sa.String(), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE providers "
            "SET brand_display_name = name, brand_primary_color = '#111827' "
            "WHERE brand_display_name IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("providers", "support_contact")
    op.drop_column("providers", "brand_primary_color")
    op.drop_column("providers", "brand_logo_url")
    op.drop_column("providers", "brand_display_name")
