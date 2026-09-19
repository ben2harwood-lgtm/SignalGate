"""Hash customer EA licence credentials.

Revision ID: 20260919_0007
Revises: 20260919_0006

This security migration deliberately removes recoverable plaintext licences.
A downgrade can restore the old schema shape but cannot recover the former
raw credentials; customer licences must be reissued after such a rollback.
"""
from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa

revision = "20260919_0007"
down_revision = "20260919_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("license_key_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("license_key_last4", sa.String(length=4), nullable=True),
    )
    op.create_index(
        "ix_users_license_key_hash",
        "users",
        ["license_key_hash"],
        unique=True,
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, license_key FROM users "
            "WHERE license_key IS NOT NULL AND license_key <> '' "
            "ORDER BY id"
        )
    ).mappings().all()
    for row in rows:
        raw = row["license_key"]
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE users "
                "SET license_key_hash=:digest, "
                "    license_key_last4=:last4, "
                "    license_key=NULL "
                "WHERE id=:user_id"
            ),
            {
                "digest": digest,
                "last4": raw[-4:],
                "user_id": row["id"],
            },
        )


def downgrade() -> None:
    # Raw credentials cannot and must not be reconstructed from their hashes.
    # The legacy license_key column remains present from the historical schema
    # and stays NULL; operators must reissue credentials after rollback.
    op.drop_index("ix_users_license_key_hash", table_name="users")
    op.drop_column("users", "license_key_last4")
    op.drop_column("users", "license_key_hash")
