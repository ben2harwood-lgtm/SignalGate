"""Disposable PostgreSQL 0011 interruption/rollback proof; no real identities."""
from __future__ import annotations

import importlib.util
import os
import re
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

pytest.importorskip("alembic", reason="Hosted migration dependency required")
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


_REVISION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261101_0011_source_authorization_epoch.py"
)


def test_postgresql_source_epoch_partial_backfill_rolls_back_before_retry() -> None:
    """A failed epoch backfill must not strand a half-upgraded source table."""
    url = os.environ.get("SIGNALGATE_TEST_DATABASE_URL")
    if not url or sa.engine.make_url(url).get_backend_name() != "postgresql":
        pytest.skip("Dedicated PostgreSQL test URL required; never use DATABASE_URL")

    from app.config import sqlalchemy_driver_url

    engine = sa.create_engine(sqlalchemy_driver_url(url))
    try:
        with engine.begin() as conn:
            # All tables shadow application tables in this connection alone.
            # Neither this test nor the migration touches persistent bindings.
            conn.exec_driver_sql("CREATE TEMPORARY TABLE providers (id TEXT PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TEMPORARY TABLE feeds (id TEXT PRIMARY KEY)")
            conn.exec_driver_sql("INSERT INTO providers (id) VALUES ('P1'), ('P2')")
            conn.exec_driver_sql("INSERT INTO feeds (id) VALUES ('F1'), ('F2')")
            conn.exec_driver_sql(
                "CREATE TEMPORARY TABLE provider_source_bindings ("
                "id TEXT PRIMARY KEY, "
                "provider_id TEXT NOT NULL REFERENCES providers(id), "
                "feed_id TEXT NOT NULL REFERENCES feeds(id), "
                "source_type TEXT NOT NULL, external_identity TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TIMESTAMP NOT NULL, "
                "updated_at TIMESTAMP NOT NULL, "
                "CONSTRAINT uq_provider_source_external_identity "
                "UNIQUE (source_type, external_identity))"
            )
            conn.exec_driver_sql(
                "INSERT INTO provider_source_bindings "
                "(id, provider_id, feed_id, source_type, external_identity, "
                "status, created_at, updated_at) VALUES "
                "('B1', 'P1', 'F1', 'TELEGRAM', '1001', 'ACTIVE', "
                "'2026-11-01 00:00:00', '2026-11-01 00:00:00'), "
                "('B2', 'P2', 'F2', 'TELEGRAM', '1002', 'REVOKED', "
                "'2026-11-01 00:00:00', '2026-11-01 00:00:00')"
            )
            before = conn.exec_driver_sql(
                "SELECT id, provider_id, feed_id, status "
                "FROM provider_source_bindings ORDER BY id"
            ).all()
            spec = importlib.util.spec_from_file_location("sg_epoch_0011_fault", _REVISION)
            assert spec is not None and spec.loader is not None
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            migration.op = Operations(MigrationContext.configure(conn))

            calls = 0

            def fail_second_epoch(size: int) -> str:
                nonlocal calls
                assert size == 16
                calls += 1
                if calls == 2:
                    raise RuntimeError("synthetic second-epoch interruption")
                return "0" * 31 + "1"

            migration.secrets = SimpleNamespace(token_hex=fail_second_epoch)
            with pytest.raises(RuntimeError, match="second-epoch interruption"):
                # PostgreSQL DDL and first UPDATE must roll back together.
                with conn.begin_nested():
                    migration.upgrade()
            assert calls == 2, "Fault must occur after one row was updated"
            assert "authorization_epoch" not in {
                col["name"]
                for col in sa.inspect(conn).get_columns("provider_source_bindings")
            }, "Failed migration left its nullable column behind"
            assert conn.exec_driver_sql(
                "SELECT id, provider_id, feed_id, status "
                "FROM provider_source_bindings ORDER BY id"
            ).all() == before

            # Retry the *same migration*, not a patched approximation.
            migration.secrets = secrets
            migration.upgrade()
            columns = {
                col["name"]: col
                for col in sa.inspect(conn).get_columns("provider_source_bindings")
            }
            assert columns["authorization_epoch"]["nullable"] is False
            rows = conn.exec_driver_sql(
                "SELECT id, authorization_epoch FROM provider_source_bindings ORDER BY id"
            ).all()
            assert [row[0] for row in rows] == ["B1", "B2"]
            assert all(re.fullmatch(r"[0-9a-f]{32}", row[1]) for row in rows)
            assert len({row[1] for row in rows}) == 2
            migration.downgrade()
            assert "authorization_epoch" not in {
                col["name"]
                for col in sa.inspect(conn).get_columns("provider_source_bindings")
            }
            assert conn.exec_driver_sql(
                "SELECT id, provider_id, feed_id, status "
                "FROM provider_source_bindings ORDER BY id"
            ).all() == before
    finally:
        engine.dispose()
