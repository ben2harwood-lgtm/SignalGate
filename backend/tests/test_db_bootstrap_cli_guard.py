"""Non-destructive CLI bootstrap preflight regressions (issue #108 partial guard)."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (ROOT / "scripts" / "init_db.py", ROOT / "scripts" / "seed_settings.py")


def _configure(monkeypatch, database_url: str, *, licensed: bool = False, demo: bool = True):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REQUIRE_LICENSE", "true" if licensed else "false")
    monkeypatch.setenv("DEMO_ONLY_MODE", "true" if demo else "false")


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://operator:synthetic-not-a-secret@localhost/signalgate",
        "postgres://operator:synthetic-not-a-secret@localhost/signalgate",
        "mysql://operator:synthetic-not-a-secret@localhost/signalgate",
        "sqlite:///:memory:",
        "sqlite:///file:signalgate.db?uri=true",
        "sqlite://",
        "not-a-database-url",
    ),
)
def test_unlicensed_cli_rejects_nonfile_or_non_sqlite(monkeypatch, database_url):
    _configure(monkeypatch, database_url)
    with pytest.raises(RuntimeError, match="Refusing CLI bootstrap") as error:
        Settings().validate_cli_bootstrap()
    assert "synthetic-not-a-secret" not in str(error.value)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://operator:synthetic-not-a-secret@localhost/signalgate",
        "postgres://operator:synthetic-not-a-secret@localhost/signalgate",
    ),
)
def test_cli_refuses_unlicensed_postgres_before_schema_or_seed(
    monkeypatch, script, database_url
):
    from app import database, main

    _configure(monkeypatch, database_url)
    actions = []

    def unexpected(*args, **kwargs):
        actions.append("database mutation attempted")
        raise AssertionError("Bootstrap attempted a database mutation")

    # Tests must never connect, mutate, or depend on the synthetic Postgres URL.
    monkeypatch.setattr(database, "init_db", unexpected)
    monkeypatch.setattr(database.Base.metadata, "create_all", unexpected)
    monkeypatch.setattr(main, "seed_settings", unexpected)
    entrypoint = runpy.run_path(str(script), run_name="bootstrap_preflight_test")["main"]

    with pytest.raises(RuntimeError, match="Refusing CLI bootstrap") as error:
        entrypoint()
    assert "synthetic-not-a-secret" not in str(error.value)
    assert actions == []


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_cli_refuses_live_mode_before_schema_or_seed(monkeypatch, script):
    from app import database, main

    _configure(monkeypatch, "sqlite:///./signalgate.db", demo=False)
    monkeypatch.setattr(database, "init_db", lambda: pytest.fail("init_db called"))
    monkeypatch.setattr(main, "seed_settings", lambda: pytest.fail("seed called"))
    entrypoint = runpy.run_path(str(script), run_name="bootstrap_preflight_test")["main"]

    with pytest.raises(RuntimeError, match="DEMO ONLY"):
        entrypoint()


@pytest.mark.parametrize("database_url", ("sqlite:///./signalgate.db", "sqlite:///./other-local.db"))
def test_valid_file_backed_local_sqlite_passes_preflight(monkeypatch, database_url):
    _configure(monkeypatch, database_url)
    Settings().validate_cli_bootstrap()


@pytest.mark.parametrize(
    "database_url",
    (
        "postgresql://operator:synthetic-not-a-secret@localhost/signalgate",
        "postgres://operator:synthetic-not-a-secret@localhost/signalgate",
    ),
)
def test_properly_configured_hosted_preflight_still_passes_without_connecting(
    monkeypatch, database_url
):
    _configure(monkeypatch, database_url, licensed=True)
    monkeypatch.setenv("BACKEND_BASE_URL", "https://demo.example.test")
    monkeypatch.setenv("EA_API_KEY", "e" * 40)
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("REGISTRATION_API_KEY", "r" * 40)
    # Hosted migration version is checked in app.database.init_db(), not here.
    Settings().validate_cli_bootstrap()


def test_hosted_bootstrap_refuses_weak_secret_without_connecting(monkeypatch):
    _configure(monkeypatch, "postgresql://user:synthetic@localhost/db", licensed=True)
    monkeypatch.setenv("BACKEND_BASE_URL", "https://demo.example.test")
    monkeypatch.setenv("EA_API_KEY", "short")
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("REGISTRATION_API_KEY", "r" * 40)
    with pytest.raises(RuntimeError, match="EA_API_KEY"):
        Settings().validate_cli_bootstrap()
