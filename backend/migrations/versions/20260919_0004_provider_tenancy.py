"""Provider organisation/feed tenancy foundation.

Revision ID: 20260919_0004
Revises: 20260919_0003
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0004"
down_revision = "20260919_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "provider_feeds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_namespace", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["provider_organizations.id"]
        ),
    )
    op.create_index(
        "ix_provider_feeds_organization_id",
        "provider_feeds",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_feeds_source_namespace",
        "provider_feeds",
        ["source_namespace"],
        unique=True,
    )

    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["provider_organizations.id"]
        ),
    )
    op.create_index(
        "ix_provider_credentials_organization_id",
        "provider_credentials",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_credentials_key_hash",
        "provider_credentials",
        ["key_hash"],
        unique=True,
    )

    op.create_table(
        "feed_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("feed_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["provider_feeds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("feed_id", "user_id", name="uq_feed_subscription"),
    )
    op.create_index(
        "ix_feed_subscriptions_feed_id",
        "feed_subscriptions",
        ["feed_id"],
        unique=False,
    )
    op.create_index(
        "ix_feed_subscriptions_user_id",
        "feed_subscriptions",
        ["user_id"],
        unique=False,
    )

    op.add_column(
        "signals",
        sa.Column("feed_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_signals_feed_id_provider_feeds",
        "signals",
        "provider_feeds",
        ["feed_id"],
        ["id"],
    )
    op.create_index("ix_signals_feed_id", "signals", ["feed_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signals_feed_id", table_name="signals")
    op.drop_constraint(
        "fk_signals_feed_id_provider_feeds", "signals", type_="foreignkey"
    )
    op.drop_column("signals", "feed_id")

    op.drop_index("ix_feed_subscriptions_user_id", table_name="feed_subscriptions")
    op.drop_index("ix_feed_subscriptions_feed_id", table_name="feed_subscriptions")
    op.drop_table("feed_subscriptions")

    op.drop_index(
        "ix_provider_credentials_key_hash", table_name="provider_credentials"
    )
    op.drop_index(
        "ix_provider_credentials_organization_id", table_name="provider_credentials"
    )
    op.drop_table("provider_credentials")

    op.drop_index(
        "ix_provider_feeds_source_namespace", table_name="provider_feeds"
    )
    op.drop_index(
        "ix_provider_feeds_organization_id", table_name="provider_feeds"
    )
    op.drop_table("provider_feeds")
    op.drop_table("provider_organizations")
