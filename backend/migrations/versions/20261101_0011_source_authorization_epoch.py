"""Renew source-preview authority after every one-time Telegram connection.

Revision ID: 20261101_0011
Revises: 20260919_0010

Backfill separate random generations for existing bindings; do not reuse row
IDs, timestamps, invitation plaintext, or the previous provider/feed tuple.
"""
from __future__ import annotations

import secrets

from alembic import op
import sqlalchemy as sa

revision = "20261101_0011"
down_revision = "20260919_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_source_bindings",
        sa.Column("authorization_epoch", sa.String(length=32), nullable=True),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM provider_source_bindings")).all()
    for (binding_id,) in rows:
        bind.execute(
            sa.text(
                "UPDATE provider_source_bindings SET authorization_epoch=:epoch "
                "WHERE id=:binding_id"
            ),
            {"epoch": secrets.token_hex(16), "binding_id": binding_id},
        )
    with op.batch_alter_table("provider_source_bindings") as batch:
        batch.alter_column(
            "authorization_epoch",
            existing_type=sa.String(length=32),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_source_bindings") as batch:
        batch.drop_column("authorization_epoch")
