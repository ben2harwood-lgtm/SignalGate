"""Provider Edition multi-tenant ownership model.

Revision ID: 20260919_0004
Revises: 20260919_0003
"""
from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa

revision = "20260919_0004"
down_revision = "20260919_0003"
branch_labels = None
depends_on = None

LEGACY_ORG_ID = "ORG-LEGACY"
LEGACY_PROVIDER_ID = "PRV-LEGACY"
LEGACY_FEED_ID = "FED-LEGACY"


def _legacy_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-LEGACY-{digest}"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "providers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint("organization_id", "slug", name="uq_provider_org_slug"),
    )
    op.create_index("ix_providers_organization_id", "providers", ["organization_id"], unique=False)

    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
    )
    op.create_index("ix_provider_credentials_provider_id", "provider_credentials", ["provider_id"], unique=False)
    op.create_index("ix_provider_credentials_key_hash", "provider_credentials", ["key_hash"], unique=True)

    op.create_table(
        "feeds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_namespace", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.UniqueConstraint("provider_id", "source_namespace", name="uq_feed_provider_source"),
    )
    op.create_index("ix_feeds_provider_id", "feeds", ["provider_id"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("feed_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("feed_id", "user_id", name="uq_subscription_feed_user"),
    )
    op.create_index("ix_subscriptions_provider_id", "subscriptions", ["provider_id"], unique=False)
    op.create_index("ix_subscriptions_feed_id", "subscriptions", ["feed_id"], unique=False)
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"], unique=False)

    op.create_table(
        "trading_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("provider_id", "user_id", name="uq_trading_account_provider_user"),
    )
    op.create_index("ix_trading_accounts_provider_id", "trading_accounts", ["provider_id"], unique=False)
    op.create_index("ix_trading_accounts_user_id", "trading_accounts", ["user_id"], unique=False)

    op.add_column("signals", sa.Column("provider_id", sa.String(), nullable=True))
    op.add_column("signals", sa.Column("feed_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_signals_provider_id", "signals", "providers", ["provider_id"], ["id"])
    op.create_foreign_key("fk_signals_feed_id", "signals", "feeds", ["feed_id"], ["id"])
    op.create_index("ix_signals_provider_id", "signals", ["provider_id"], unique=False)
    op.create_index("ix_signals_feed_id", "signals", ["feed_id"], unique=False)

    op.add_column("commands", sa.Column("provider_id", sa.String(), nullable=True))
    op.add_column("commands", sa.Column("feed_id", sa.String(), nullable=True))
    op.add_column("commands", sa.Column("account_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_commands_provider_id", "commands", "providers", ["provider_id"], ["id"])
    op.create_foreign_key("fk_commands_feed_id", "commands", "feeds", ["feed_id"], ["id"])
    op.create_foreign_key("fk_commands_account_id", "commands", "trading_accounts", ["account_id"], ["id"])
    op.create_index("ix_commands_provider_id", "commands", ["provider_id"], unique=False)
    op.create_index("ix_commands_feed_id", "commands", ["feed_id"], unique=False)
    op.create_index("ix_commands_account_id", "commands", ["account_id"], unique=False)

    bind = op.get_bind()
    now = bind.execute(sa.text("SELECT CURRENT_TIMESTAMP")).scalar_one()
    bind.execute(
        sa.text(
            """
            INSERT INTO organizations (id, name, slug, status, created_at, updated_at)
            VALUES (:id, :name, :slug, 'ACTIVE', :now, :now)
            """
        ),
        {"id": LEGACY_ORG_ID, "name": "Legacy SignalGate", "slug": "legacy", "now": now},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO providers (id, organization_id, name, slug, status, paused, created_at, updated_at)
            VALUES (:id, :org, :name, :slug, 'ACTIVE', false, :now, :now)
            """
        ),
        {"id": LEGACY_PROVIDER_ID, "org": LEGACY_ORG_ID, "name": "Legacy Provider", "slug": "legacy", "now": now},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO feeds (id, provider_id, name, source_namespace, status, paused, created_at, updated_at)
            VALUES (:id, :provider, :name, :namespace, 'ACTIVE', false, :now, :now)
            """
        ),
        {"id": LEGACY_FEED_ID, "provider": LEGACY_PROVIDER_ID, "name": "Legacy Feed", "namespace": "LEGACY", "now": now},
    )

    users = bind.execute(sa.text("SELECT id FROM users ORDER BY id")).mappings().all()
    for row in users:
        user_id = row["id"]
        account_id = _legacy_id("ACC", user_id)
        subscription_id = _legacy_id("SUB", user_id)
        bind.execute(
            sa.text(
                """
                INSERT INTO trading_accounts (id, provider_id, user_id, label, status, created_at, updated_at)
                VALUES (:id, :provider, :user_id, 'Primary', 'ACTIVE', :now, :now)
                """
            ),
            {"id": account_id, "provider": LEGACY_PROVIDER_ID, "user_id": user_id, "now": now},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO subscriptions (id, provider_id, feed_id, user_id, status, created_at, updated_at)
                VALUES (:id, :provider, :feed, :user_id, 'ACTIVE', :now, :now)
                """
            ),
            {"id": subscription_id, "provider": LEGACY_PROVIDER_ID, "feed": LEGACY_FEED_ID, "user_id": user_id, "now": now},
        )

    bind.execute(
        sa.text("UPDATE signals SET provider_id=:provider, feed_id=:feed WHERE provider_id IS NULL"),
        {"provider": LEGACY_PROVIDER_ID, "feed": LEGACY_FEED_ID},
    )
    bind.execute(
        sa.text(
            """
            UPDATE commands AS c
            SET provider_id=:provider,
                feed_id=:feed,
                account_id=a.id
            FROM trading_accounts AS a
            WHERE a.provider_id=:provider
              AND a.user_id=c.user_id
              AND c.provider_id IS NULL
            """
        ),
        {"provider": LEGACY_PROVIDER_ID, "feed": LEGACY_FEED_ID},
    )


def downgrade() -> None:
    op.drop_index("ix_commands_account_id", table_name="commands")
    op.drop_index("ix_commands_feed_id", table_name="commands")
    op.drop_index("ix_commands_provider_id", table_name="commands")
    op.drop_constraint("fk_commands_account_id", "commands", type_="foreignkey")
    op.drop_constraint("fk_commands_feed_id", "commands", type_="foreignkey")
    op.drop_constraint("fk_commands_provider_id", "commands", type_="foreignkey")
    op.drop_column("commands", "account_id")
    op.drop_column("commands", "feed_id")
    op.drop_column("commands", "provider_id")

    op.drop_index("ix_signals_feed_id", table_name="signals")
    op.drop_index("ix_signals_provider_id", table_name="signals")
    op.drop_constraint("fk_signals_feed_id", "signals", type_="foreignkey")
    op.drop_constraint("fk_signals_provider_id", "signals", type_="foreignkey")
    op.drop_column("signals", "feed_id")
    op.drop_column("signals", "provider_id")

    op.drop_index("ix_trading_accounts_user_id", table_name="trading_accounts")
    op.drop_index("ix_trading_accounts_provider_id", table_name="trading_accounts")
    op.drop_table("trading_accounts")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_feed_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_provider_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_feeds_provider_id", table_name="feeds")
    op.drop_table("feeds")
    op.drop_index("ix_provider_credentials_key_hash", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_provider_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
    op.drop_index("ix_providers_organization_id", table_name="providers")
    op.drop_table("providers")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
