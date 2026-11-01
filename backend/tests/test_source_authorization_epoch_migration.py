"""Synthetic populated-binding migration checks; no real provider or broker data."""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
import sqlalchemy as sa


_REVISION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261101_0011_source_authorization_epoch.py"
)


def _exercise_populated_migration(conn, *, postgres: bool) -> None:
    """Prove distinct non-null epochs on old active AND revoked identities."""
    spec = importlib.util.spec_from_file_location("sg_source_epoch_0011", _REVISION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    temporary = "TEMPORARY " if postgres else ""
    conn.exec_driver_sql(
        f"CREATE {temporary}TABLE provider_source_bindings ("
        "id VARCHAR(80) NOT NULL PRIMARY KEY, "
        "status VARCHAR(20) NOT NULL)"
    )
    conn.exec_driver_sql(
        "INSERT INTO provider_source_bindings (id, status) VALUES "
        "('BIND-A', 'ACTIVE'), ('BIND-B', 'REVOKED'), ('BIND-C', 'ACTIVE')"
    )
    migration.op = Operations(MigrationContext.configure(conn))
    migration.upgrade()
    rows = conn.exec_driver_sql(
        "SELECT id, status, authorization_epoch "
        "FROM provider_source_bindings ORDER BY id"
    ).all()
    assert [row[0] for row in rows] == ["BIND-A", "BIND-B", "BIND-C"]
    assert [row[1] for row in rows] == ["ACTIVE", "REVOKED", "ACTIVE"]
    original_epochs = [row[2] for row in rows]
    assert all(re.fullmatch(r"[0-9a-f]{32}", epoch) for epoch in original_epochs)
    assert len(set(original_epochs)) == len(rows)
    columns = {
        column["name"]: column
        for column in sa.inspect(conn).get_columns("provider_source_bindings")
    }
    assert columns["authorization_epoch"]["nullable"] is False

    migration.downgrade()
    assert "authorization_epoch" not in {
        column["name"]
        for column in sa.inspect(conn).get_columns("provider_source_bindings")
    }
    migration.upgrade()
    regenerated_epochs = [
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT authorization_epoch FROM provider_source_bindings ORDER BY id"
        )
    ]
    assert len(set(regenerated_epochs)) == len(rows)
    assert all(
        new != old for new, old in zip(regenerated_epochs, original_epochs)
    )


def test_populated_source_epoch_migration_on_isolated_sqlite() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as conn:
            _exercise_populated_migration(conn, postgres=False)
    finally:
        engine.dispose()


def test_populated_source_epoch_migration_on_temporary_postgresql() -> None:
    """Run only against CI's test database; TEMP table shadows app tables."""
    url = os.environ.get("SIGNALGATE_TEST_DATABASE_URL")
    if not url or sa.engine.make_url(url).get_backend_name() != "postgresql":
        pytest.skip("No dedicated PostgreSQL test URL; never use DATABASE_URL")
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            _exercise_populated_migration(conn, postgres=True)
    finally:
        engine.dispose()
