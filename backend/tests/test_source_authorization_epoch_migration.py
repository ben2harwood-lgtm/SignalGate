"""Synthetic populated-binding migration checks; no real provider or broker data."""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest
import sqlalchemy as sa

# The lightweight backend job intentionally lacks hosted Alembic dependencies.
# Run the populated-migration assertions in the hosted PostgreSQL CI job.
pytest.importorskip("alembic", reason="Hosted migration dependencies required")
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


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
        "provider_id VARCHAR(80) NOT NULL, "
        "feed_id VARCHAR(80) NOT NULL, "
        "source_type VARCHAR(20) NOT NULL, "
        "external_identity VARCHAR(40) NOT NULL, "
        "status VARCHAR(20) NOT NULL, "
        "CONSTRAINT uq_provider_source_external_identity "
        "UNIQUE (source_type, external_identity))"
    )
    # Revision 0009 also builds these three search/tenancy indexes. On SQLite,
    # 0011's batch table rebuild must retain them, not merely its UNIQUE rule.
    expected_indexes = {
        "ix_provider_source_bindings_provider_id": ["provider_id"],
        "ix_provider_source_bindings_feed_id": ["feed_id"],
        "ix_provider_source_bindings_external_identity": ["external_identity"],
    }
    for index_name, columns in expected_indexes.items():
        conn.exec_driver_sql(
            f"CREATE INDEX {index_name} ON provider_source_bindings ({columns[0]})"
        )

    conn.exec_driver_sql(
        "INSERT INTO provider_source_bindings "
        "(id, provider_id, feed_id, source_type, external_identity, status) VALUES "
        "('BIND-A', 'PROVIDER-A', 'FEED-A', 'TELEGRAM', '92001', 'ACTIVE'), "
        "('BIND-B', 'PROVIDER-B', 'FEED-B', 'TELEGRAM', '92002', 'REVOKED'), "
        "('BIND-C', 'PROVIDER-A', 'FEED-C', 'TELEGRAM', '92003', 'ACTIVE')"
    )
    original_scopes = conn.exec_driver_sql(
        "SELECT id, provider_id, feed_id, source_type, external_identity, status "
        "FROM provider_source_bindings ORDER BY id"
    ).all()

    def assert_unique_source_identity() -> None:
        # This pre-0011 constraint prevents two providers from owning the same
        # Telegram identity. A batch table rebuild must never silently drop it.
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                conn.exec_driver_sql(
                    "INSERT INTO provider_source_bindings "
                    "(id, provider_id, feed_id, source_type, external_identity, status) "
                    "VALUES ('BIND-D', 'OTHER', 'OTHER', 'TELEGRAM', '92001', 'ACTIVE')"
                )

    def assert_scope_preserved() -> None:
        assert conn.exec_driver_sql(
            "SELECT id, provider_id, feed_id, source_type, external_identity, status "
            "FROM provider_source_bindings ORDER BY id"
        ).all() == original_scopes
        assert_unique_source_identity()
        surviving_indexes = {
            index["name"]: index
            for index in sa.inspect(conn).get_indexes("provider_source_bindings")
        }
        for name, expected_columns in expected_indexes.items():
            assert name in surviving_indexes, f"0011 dropped pre-existing index {name}"
            assert surviving_indexes[name]["column_names"] == expected_columns
            assert surviving_indexes[name]["unique"] is False

    assert_scope_preserved()
    migration.op = Operations(MigrationContext.configure(conn))
    migration.upgrade()
    assert_scope_preserved()
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
    assert_scope_preserved()
    assert "authorization_epoch" not in {
        column["name"]
        for column in sa.inspect(conn).get_columns("provider_source_bindings")
    }
    migration.upgrade()
    assert_scope_preserved()
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
    # SQLAlchemy 2.1 defaults to psycopg, but hosted CI installs psycopg2.
    from app.config import sqlalchemy_driver_url

    engine = sa.create_engine(sqlalchemy_driver_url(url))
    try:
        with engine.begin() as conn:
            _exercise_populated_migration(conn, postgres=True)
    finally:
        engine.dispose()
