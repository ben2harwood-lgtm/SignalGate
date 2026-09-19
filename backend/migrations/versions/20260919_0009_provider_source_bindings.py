"""Tenant-bound provider source connections.

Revision ID: 20260919_0009
Revises: 20260919_0008
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0009"
down_revision = "20260919_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_source_invites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("feed_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_telegram_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"]),
    )
    op.create_index(
        "ix_provider_source_invites_provider_id",
        "provider_source_invites",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_source_invites_feed_id",
        "provider_source_invites",
        ["feed_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_source_invites_token_hash",
        "provider_source_invites",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "provider_source_bindings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("feed_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("external_identity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"]),
        sa.UniqueConstraint(
            "source_type",
            "external_identity",
            name="uq_provider_source_external_identity",
        ),
    )
    op.create_index(
        "ix_provider_source_bindings_provider_id",
        "provider_source_bindings",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_source_bindings_feed_id",
        "provider_source_bindings",
        ["feed_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_source_bindings_external_identity",
        "provider_source_bindings",
        ["external_identity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_source_bindings_external_identity",
        table_name="provider_source_bindings",
    )
    op.drop_index(
        "ix_provider_source_bindings_feed_id",
        table_name="provider_source_bindings",
    )
    op.drop_index(
        "ix_provider_source_bindings_provider_id",
        table_name="provider_source_bindings",
    )
    op.drop_table("provider_source_bindings")
    op.drop_index(
        "ix_provider_source_invites_token_hash",
        table_name="provider_source_invites",
    )
    op.drop_index(
        "ix_provider_source_invites_feed_id",
        table_name="provider_source_invites",
    )
    op.drop_index(
        "ix_provider_source_invites_provider_id",
        table_name="provider_source_invites",
    )
    op.drop_table("provider_source_invites")
