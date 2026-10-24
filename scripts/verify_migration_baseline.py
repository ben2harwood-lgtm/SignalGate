#!/usr/bin/env python3
"""Read-only verifier for adopting an existing database into Alembic baseline."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

# The verifier runs from the repository root; share the same dialect choice as
# application/Alembic without changing DATABASE_URL used by libpq tools.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import sqlalchemy_driver_url  # noqa: E402

EXPECTED_COLUMNS = {
    "users": {"id","telegram_user_id","telegram_username","first_name","status","risk_percent","fixed_lot_size","license_key","created_at","updated_at"},
    "signals": {"id","source","source_message_id","raw_text","symbol","direction","entry_type","entry_price","initial_stop_loss","tp1","tp2","tp3","parser_status","parser_error","created_at","expires_at","status","edited_marker","deleted_marker"},
    "settings": {"id","key","value","updated_at"},
    "approvals": {"id","signal_id","user_id","decision","created_at","status"},
    "commands": {"id","signal_id","approval_id","user_id","symbol","direction","entry_type","entry_price","initial_stop_loss","tp1","tp2","tp3","tp1_close_percent","tp2_close_percent","tp3_close_percent","lot_size","split_ticket_demo_partial_mode","tp1_lot","tp2_lot","tp3_lot","risk_percent","status","created_at","expires_at","sent_to_ea_at","processed_at","last_error"},
    "executions": {"id","command_id","user_id","status","broker_ticket","child_tickets_json","executed_symbol","executed_direction","requested_price","executed_price","lot_size","initial_stop_loss","tp1","tp2","tp3","spread_at_execution","slippage","error_code","error_message","created_at"},
    "trade_management_events": {"id","command_id","broker_ticket","event_type","stage","requested_action","result","price","lot_size_before","lot_size_after","stop_loss_before","stop_loss_after","error_code","error_message","created_at"},
    "performance_ledger": {"id","signal_id","command_id","symbol","direction","entry_price","initial_stop_loss","tp1","tp2","tp3","result_status","r_result","max_favourable_excursion","max_adverse_excursion","signal_to_card_delay","approval_to_execution_delay","slippage","spread_at_execution","final_notes","created_at","updated_at"},
    "audit_logs": {"id","event_type","entity_type","entity_id","payload_json","created_at"},
}
EXPECTED_UNIQUE = {
    "users": {("telegram_user_id",), ("license_key",)},
    "settings": {("key",)},
    "approvals": {("signal_id", "user_id")},
}



# These constraints are material to approval, command and execution identity.
# An existing database with the right column names but no relations must NOT
# be stamped as the historical Alembic baseline.
EXPECTED_FOREIGN_KEYS = {
    "approvals": {
        (("signal_id",), "signals", ("id",)),
        (("user_id",), "users", ("id",)),
    },
    "commands": {
        (("signal_id",), "signals", ("id",)),
        (("approval_id",), "approvals", ("id",)),
        (("user_id",), "users", ("id",)),
    },
    "executions": {
        (("command_id",), "commands", ("id",)),
        (("user_id",), "users", ("id",)),
    },
    "trade_management_events": {
        (("command_id",), "commands", ("id",)),
    },
    "performance_ledger": {
        (("signal_id",), "signals", ("id",)),
        (("command_id",), "commands", ("id",)),
    },
}


def _foreign_key_sets(inspector, table):
    """Read reflected relations only; do not use ORM/metadata to fabricate them."""
    found = set()
    for row in inspector.get_foreign_keys(table):
        local = tuple(row.get("constrained_columns") or ())
        referenced = tuple(row.get("referred_columns") or ())
        destination = row.get("referred_table")
        # A similarly named table in a foreign schema is not baseline proof.
        if row.get("referred_schema") not in (None, inspector.default_schema_name):
            continue
        if local and referenced and destination:
            found.add((local, destination, referenced))
    return found


def _unique_sets(inspector, table):
    found = set()
    for row in inspector.get_unique_constraints(table):
        cols = tuple(row.get("column_names") or ())
        if cols:
            found.add(cols)
    for row in inspector.get_indexes(table):
        if row.get("unique"):
            cols = tuple(row.get("column_names") or ())
            if cols:
                found.add(cols)
    return found


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    inspector = inspect(create_engine(sqlalchemy_driver_url(url), future=True))
    actual_tables = set(inspector.get_table_names())
    errors = []

    for table, expected in EXPECTED_COLUMNS.items():
        if table not in actual_tables:
            errors.append(f"missing table: {table}")
            continue
        actual = {row["name"] for row in inspector.get_columns(table)}
        missing, extra = expected - actual, actual - expected
        if missing:
            errors.append(f"{table}: missing columns {sorted(missing)}")
        if extra:
            errors.append(f"{table}: unexpected columns {sorted(extra)}")
        pk = tuple(inspector.get_pk_constraint(table).get("constrained_columns") or ())
        if pk != ("id",):
            errors.append(f"{table}: expected primary key ('id',), found {pk}")

    for table, required in EXPECTED_UNIQUE.items():
        if table not in actual_tables:
            continue
        found = _unique_sets(inspector, table)
        for cols in required:
            if cols not in found:
                errors.append(f"{table}: missing unique constraint/index on {cols}")


    for table, required in EXPECTED_FOREIGN_KEYS.items():
        if table not in actual_tables:
            continue
        found = _foreign_key_sets(inspector, table)
        for local, destination, remote in sorted(required):
            if (local, destination, remote) not in found:
                errors.append(
                    f"{table}: missing foreign key {local} -> {destination}{remote}"
                )

    if errors:
        print("BASELINE VERIFICATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("BASELINE VERIFICATION PASSED")
    print("Safe next step for an existing database: alembic stamp 20260918_0001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
