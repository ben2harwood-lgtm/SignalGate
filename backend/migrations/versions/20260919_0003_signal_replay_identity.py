"""Signal source replay identity uniqueness.

Revision ID: 20260919_0003
Revises: 20260919_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0003"
down_revision = "20260919_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT source, source_message_id, COUNT(*) AS n
            FROM signals
            WHERE source_message_id IS NOT NULL
            GROUP BY source, source_message_id
            HAVING COUNT(*) > 1
            ORDER BY source, source_message_id
            LIMIT 25
            """
        )
    ).mappings().all()
    if duplicates:
        sample = ", ".join(
            f"{row['source']}:{row['source_message_id']} ({row['n']})"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot enforce signal replay identity: duplicate historical "
            f"source/message pairs require manual reconciliation first: {sample}"
        )

    op.create_unique_constraint(
        "uq_signal_source_message",
        "signals",
        ["source", "source_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_signal_source_message",
        "signals",
        type_="unique",
    )
