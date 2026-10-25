"""Migration-boundary tests."""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.engine import make_url

from app import database


def test_hosted_init_db_never_calls_create_all_and_checks_head(monkeypatch):
    create_all_called = False
    migration_checked = False

    def _unexpected_create_all(*_args, **_kwargs):
        nonlocal create_all_called
        create_all_called = True

    def _checked():
        nonlocal migration_checked
        migration_checked = True

    monkeypatch.setattr(database.settings, "require_license", True)
    monkeypatch.setattr(database.Base.metadata, "create_all", _unexpected_create_all)
    monkeypatch.setattr(database, "_assert_hosted_schema_current", _checked)

    database.init_db()
    assert create_all_called is False
    assert migration_checked is True


def test_local_demo_init_db_keeps_create_all(monkeypatch):
    called = False

    def _create_all(*_args, **_kwargs):
        nonlocal called
        called = True

    # This is explicitly a synthetic local-SQLite unit case even when the
    # full route suite runs against real isolated PostgreSQL in its CI matrix.
    # Do not relax the production non-SQLite init_db guard for this fixture.
    local_url = "sqlite:///./synthetic-local-schema-only.db"
    monkeypatch.setattr(database.settings, "require_license", False)
    monkeypatch.setattr(database.settings, "database_url", local_url)
    monkeypatch.setattr(database, "engine", SimpleNamespace(url=make_url(local_url)))
    monkeypatch.setattr(database.Base.metadata, "create_all", _create_all)

    database.init_db()
    assert called is True
