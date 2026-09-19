"""Execution lifecycle idempotency constraints.

Revision ID: 20260919_0002
Revises: 20260918_0001
"""
from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa

revision = "20260919_0002"
down_revision = "20260918_0001"
branch_labels = None
depends_on = None


def _management_key(row) -> str:
    parts = [
        row["command_id"] or "",
        row["event_type"] or "",
        row["stage"] or "",
        row["result"] or "",
        row["broker_ticket"] or "",
        row["requested_action"] or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()

    duplicate_executions = bind.execute(
        sa.text(
            """
            SELECT command_id, COUNT(*) AS n
            FROM executions
            GROUP BY command_id
            HAVING COUNT(*) > 1
            ORDER BY command_id
            LIMIT 25
            """
        )
    ).mappings().all()
    if duplicate_executions:
        sample = ", ".join(
            f"{row['command_id']} ({row['n']})" for row in duplicate_executions
        )
        raise RuntimeError(
            "Cannot enforce one execution per command: duplicate historical "
            f"executions require manual reconciliation first: {sample}"
        )

    rows = bind.execute(
        sa.text(
            """
            SELECT id, command_id, broker_ticket, event_type, stage,
                   requested_action, result
            FROM trade_management_events
            ORDER BY id
            """
        )
    ).mappings().all()

    keys: dict[str, str] = {}
    backfill: list[tuple[str, str]] = []
    for row in rows:
        key = _management_key(row)
        previous = keys.get(key)
        if previous is not None:
            raise RuntimeError(
                "Cannot enforce management-event idempotency: historical rows "
                f"{previous} and {row['id']} have the same retry identity. "
                "Reconcile them manually; migration will not delete or guess."
            )
        keys[key] = row["id"]
        backfill.append((row["id"], key))

    op.drop_index("ix_executions_command_id", table_name="executions")
    op.create_index(
        "ix_executions_command_id",
        "executions",
        ["command_id"],
        unique=True,
    )

    op.add_column(
        "trade_management_events",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )
    for event_id, key in backfill:
        bind.execute(
            sa.text(
                """
                UPDATE trade_management_events
                SET idempotency_key = :key
                WHERE id = :event_id
                """
            ),
            {"key": key, "event_id": event_id},
        )

    op.alter_column(
        "trade_management_events",
        "idempotency_key",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index(
        "ix_trade_management_events_idempotency_key",
        "trade_management_events",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trade_management_events_idempotency_key",
        table_name="trade_management_events",
    )
    op.drop_column("trade_management_events", "idempotency_key")

    op.drop_index("ix_executions_command_id", table_name="executions")
    op.create_index(
        "ix_executions_command_id",
        "executions",
        ["command_id"],
        unique=False,
    )
