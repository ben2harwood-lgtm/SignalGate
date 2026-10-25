"""Synthetic no-connect guards for the local-demo init_db trust boundary.

These tests do not contact a real PostgreSQL instance, seed a customer database,
authenticate a provider, or constitute hosted/pilot acceptance.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app import database
import app.main as main_module
from app.config import sqlalchemy_driver_url


def _fake_engine(url: str):
    # Parsing SQLAlchemy URLs has no network or database side effects.
    return SimpleNamespace(url=make_url(sqlalchemy_driver_url(url)))


def _assert_no_schema_creation(monkeypatch):
    monkeypatch.setattr(
        database.Base.metadata,
        "create_all",
        lambda *args, **kwargs: pytest.fail("create_all ran before safety preflight"),
    )
    monkeypatch.setattr(
        database,
        "_assert_hosted_schema_current",
        lambda: pytest.fail("local mode attempted hosted schema access"),
    )


@pytest.mark.parametrize(
    ("configured", "engine_url"),
    [
        ("postgresql://fake:secret@db.invalid/demo", "postgresql://fake:secret@db.invalid/demo"),
        ("postgres://fake:secret@db.invalid/demo", "postgresql://fake:secret@db.invalid/demo"),
        ("sqlite:///./safe.db", "postgresql://fake:secret@db.invalid/demo"),
        ("postgresql://fake:secret@db.invalid/demo", "sqlite:///./safe.db"),
        ("sqlite:///./other.db", "sqlite:///./safe.db"),
        ("not-a-database-url", "sqlite:///./safe.db"),
    ],
)
def test_direct_local_init_refuses_non_sqlite_or_drift_without_schema_io(
    monkeypatch, configured, engine_url
):
    _assert_no_schema_creation(monkeypatch)
    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(require_license=False, database_url=configured),
    )
    monkeypatch.setattr(database, "engine", _fake_engine(engine_url))
    with pytest.raises(RuntimeError, match="matching SQLite settings") as error:
        database.init_db()
    assert "secret" not in str(error.value)


def test_matching_local_sqlite_still_creates_schema(monkeypatch):
    engine = _fake_engine("sqlite:///./safe.db")
    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(require_license=False, database_url="sqlite:///./safe.db"),
    )
    monkeypatch.setattr(database, "engine", engine)
    called = []
    monkeypatch.setattr(
        database.Base.metadata,
        "create_all",
        lambda *, bind: called.append(bind),
    )
    monkeypatch.setattr(
        database,
        "_assert_hosted_schema_current",
        lambda: pytest.fail("SQLite demo attempted hosted schema check"),
    )
    database.init_db()
    assert called == [engine]


def test_licensed_postgres_still_uses_hosted_schema_verifier(monkeypatch):
    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(
            require_license=True,
            database_url="postgresql://fake:secret@db.invalid/demo",
        ),
    )
    monkeypatch.setattr(
        database,
        "engine",
        _fake_engine("postgresql://fake:secret@db.invalid/demo"),
    )
    called = []
    monkeypatch.setattr(database, "_assert_hosted_schema_current", lambda: called.append(True))
    monkeypatch.setattr(
        database.Base.metadata,
        "create_all",
        lambda *args, **kwargs: pytest.fail("hosted create_all must never run"),
    )
    database.init_db()
    assert called == [True]


def test_actual_asgi_startup_rejects_unlicensed_postgres_before_seed(monkeypatch):
    _assert_no_schema_creation(monkeypatch)
    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(
            require_license=False,
            database_url="postgresql://fake:secret@db.invalid/demo",
        ),
    )
    monkeypatch.setattr(
        database,
        "engine",
        _fake_engine("postgresql://fake:secret@db.invalid/demo"),
    )
    monkeypatch.setattr(
        main_module,
        "seed_settings",
        lambda: pytest.fail("seed_settings ran after failed init preflight"),
    )
    # No client fixture here: exercise the real application lifespan rather
    # than the explicit PostgreSQL route-test fixture exception.
    with pytest.raises(RuntimeError, match="matching SQLite settings"):
        with TestClient(main_module.app):
            pytest.fail("unlicensed PostgreSQL app started")
