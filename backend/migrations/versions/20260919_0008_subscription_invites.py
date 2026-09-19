"""Subscriber-consent subscription invites.

Revision ID: 20260919_0008
Revises: 20260919_0007
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0008"
down_revision = "20260919_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_invites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("feed_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"]),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_subscription_invites_provider_id",
        "subscription_invites",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_invites_feed_id",
        "subscription_invites",
        ["feed_id"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_invites_token_hash",
        "subscription_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_subscription_invites_accepted_user_id",
        "subscription_invites",
        ["accepted_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_invites_accepted_user_id",
        table_name="subscription_invites",
    )
    op.drop_index(
        "ix_subscription_invites_token_hash",
        table_name="subscription_invites",
    )
    op.drop_index(
        "ix_subscription_invites_feed_id",
        table_name="subscription_invites",
    )
    op.drop_index(
        "ix_subscription_invites_provider_id",
        table_name="subscription_invites",
    )
    op.drop_table("subscription_invites")
