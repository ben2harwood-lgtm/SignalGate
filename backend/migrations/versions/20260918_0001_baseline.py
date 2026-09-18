"""SignalGate hosted PostgreSQL baseline.

This migration is intentionally static. Do not replace it with
Base.metadata.create_all(): a historical migration must not change when future
ORM models change.

Revision ID: 20260918_0001
Revises:
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260918_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("telegram_user_id", sa.String(), nullable=False),
        sa.Column("telegram_username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("risk_percent", sa.Float(), nullable=True),
        sa.Column("fixed_lot_size", sa.Float(), nullable=False),
        sa.Column("license_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)
    op.create_index("ix_users_license_key", "users", ["license_key"], unique=True)

    op.create_table(
        "signals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("entry_type", sa.String(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("initial_stop_loss", sa.Float(), nullable=True),
        sa.Column("tp1", sa.Float(), nullable=True),
        sa.Column("tp2", sa.Float(), nullable=True),
        sa.Column("tp3", sa.Float(), nullable=True),
        sa.Column("parser_status", sa.String(), nullable=False),
        sa.Column("parser_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("edited_marker", sa.Boolean(), nullable=False),
        sa.Column("deleted_marker", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_settings_key", "settings", ["key"], unique=True)

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("signal_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("signal_id", "user_id", name="uq_signal_user_approval"),
    )
    op.create_index("ix_approvals_signal_id", "approvals", ["signal_id"], unique=False)
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"], unique=False)

    op.create_table(
        "commands",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("signal_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("initial_stop_loss", sa.Float(), nullable=False),
        sa.Column("tp1", sa.Float(), nullable=False),
        sa.Column("tp2", sa.Float(), nullable=True),
        sa.Column("tp3", sa.Float(), nullable=True),
        sa.Column("tp1_close_percent", sa.Integer(), nullable=False),
        sa.Column("tp2_close_percent", sa.Integer(), nullable=False),
        sa.Column("tp3_close_percent", sa.Integer(), nullable=False),
        sa.Column("lot_size", sa.Float(), nullable=False),
        sa.Column("split_ticket_demo_partial_mode", sa.Boolean(), nullable=False),
        sa.Column("tp1_lot", sa.Float(), nullable=True),
        sa.Column("tp2_lot", sa.Float(), nullable=True),
        sa.Column("tp3_lot", sa.Float(), nullable=True),
        sa.Column("risk_percent", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("sent_to_ea_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_commands_signal_id", "commands", ["signal_id"], unique=False)
    op.create_index("ix_commands_approval_id", "commands", ["approval_id"], unique=False)
    op.create_index("ix_commands_user_id", "commands", ["user_id"], unique=False)

    op.create_table(
        "executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("broker_ticket", sa.String(), nullable=True),
        sa.Column("child_tickets_json", sa.Text(), nullable=True),
        sa.Column("executed_symbol", sa.String(), nullable=True),
        sa.Column("executed_direction", sa.String(), nullable=True),
        sa.Column("requested_price", sa.Float(), nullable=True),
        sa.Column("executed_price", sa.Float(), nullable=True),
        sa.Column("lot_size", sa.Float(), nullable=True),
        sa.Column("initial_stop_loss", sa.Float(), nullable=True),
        sa.Column("tp1", sa.Float(), nullable=True),
        sa.Column("tp2", sa.Float(), nullable=True),
        sa.Column("tp3", sa.Float(), nullable=True),
        sa.Column("spread_at_execution", sa.Float(), nullable=True),
        sa.Column("slippage", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_executions_command_id", "executions", ["command_id"], unique=False)
    op.create_index("ix_executions_user_id", "executions", ["user_id"], unique=False)

    op.create_table(
        "trade_management_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("broker_ticket", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("requested_action", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("lot_size_before", sa.Float(), nullable=True),
        sa.Column("lot_size_after", sa.Float(), nullable=True),
        sa.Column("stop_loss_before", sa.Float(), nullable=True),
        sa.Column("stop_loss_after", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"]),
    )
    op.create_index(
        "ix_trade_management_events_command_id",
        "trade_management_events",
        ["command_id"],
        unique=False,
    )

    op.create_table(
        "performance_ledger",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("signal_id", sa.String(), nullable=False),
        sa.Column("command_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("initial_stop_loss", sa.Float(), nullable=True),
        sa.Column("tp1", sa.Float(), nullable=True),
        sa.Column("tp2", sa.Float(), nullable=True),
        sa.Column("tp3", sa.Float(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=False),
        sa.Column("r_result", sa.Float(), nullable=True),
        sa.Column("max_favourable_excursion", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("signal_to_card_delay", sa.Float(), nullable=True),
        sa.Column("approval_to_execution_delay", sa.Float(), nullable=True),
        sa.Column("slippage", sa.Float(), nullable=True),
        sa.Column("spread_at_execution", sa.Float(), nullable=True),
        sa.Column("final_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"]),
    )
    op.create_index(
        "ix_performance_ledger_signal_id",
        "performance_ledger",
        ["signal_id"],
        unique=False,
    )
    op.create_index(
        "ix_performance_ledger_command_id",
        "performance_ledger",
        ["command_id"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("ix_performance_ledger_command_id", table_name="performance_ledger")
    op.drop_index("ix_performance_ledger_signal_id", table_name="performance_ledger")
    op.drop_table("performance_ledger")
    op.drop_index("ix_trade_management_events_command_id", table_name="trade_management_events")
    op.drop_table("trade_management_events")
    op.drop_index("ix_executions_user_id", table_name="executions")
    op.drop_index("ix_executions_command_id", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_commands_user_id", table_name="commands")
    op.drop_index("ix_commands_approval_id", table_name="commands")
    op.drop_index("ix_commands_signal_id", table_name="commands")
    op.drop_table("commands")
    op.drop_index("ix_approvals_user_id", table_name="approvals")
    op.drop_index("ix_approvals_signal_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_settings_key", table_name="settings")
    op.drop_table("settings")
    op.drop_table("signals")
    op.drop_index("ix_users_license_key", table_name="users")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
