"""Tamper-evident audit hash chain.

Revision ID: 20260919_0010
Revises: 20260919_0009
"""
from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision = "20260919_0010"
down_revision = "20260919_0009"
branch_labels = None
depends_on = None


def _record_hash(row, prev_hash: str | None) -> str:
    created_at = row["created_at"]
    material = {
        "id": row["id"],
        "event_type": row["event_type"],
        "entity_type": row["entity_type"] or "",
        "entity_id": row["entity_id"] or "",
        "payload_json": row["payload_json"] or "",
        "created_at": created_at.isoformat(timespec="microseconds"),
        "prev_hash": prev_hash or "",
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("record_hash", sa.String(length=64), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, event_type, entity_type, entity_id, payload_json, created_at
            FROM audit_logs
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings().all()

    prev_hash = None
    for row in rows:
        digest = _record_hash(row, prev_hash)
        bind.execute(
            sa.text(
                """
                UPDATE audit_logs
                SET prev_hash=:prev_hash, record_hash=:record_hash
                WHERE id=:row_id
                """
            ),
            {
                "prev_hash": prev_hash,
                "record_hash": digest,
                "row_id": row["id"],
            },
        )
        prev_hash = digest

    op.alter_column(
        "audit_logs",
        "record_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index(
        "ix_audit_logs_record_hash",
        "audit_logs",
        ["record_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_record_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "record_hash")
    op.drop_column("audit_logs", "prev_hash")
