"""Offline tests for the packaged demo-only hosted entrypoint.

No Uvicorn server, PostgreSQL connection, provider or broker is started.
The production CLI remains guarded even if env values are misconfigured.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app import hosted_entrypoint


def _configured_hosted(monkeypatch):
    monkeypatch.setenv("DEMO_ONLY_MODE", "true")
    monkeypatch.setenv("REQUIRE_LICENSE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example:synthetic@localhost/test")
    monkeypatch.setenv("BACKEND_BASE_URL", "https://demo.example.test")
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")  # explicit staging container interface
    monkeypatch.setenv("EA_API_KEY", "e" * 40)
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("REGISTRATION_API_KEY", "r" * 40)


@pytest.mark.parametrize("database_url", [
    "sqlite:///./local.db",
    "postgresql://example:synthetic@localhost/test",
    "postgres://example:synthetic@localhost/test",
])
def test_hosted_image_refuses_local_auth_even_with_database_config(monkeypatch, database_url):
    _configured_hosted(monkeypatch)
    monkeypatch.setenv("REQUIRE_LICENSE", "false")
    monkeypatch.setenv("DATABASE_URL", database_url)
    with pytest.raises(RuntimeError, match="requires REQUIRE_LICENSE=true"):
        hosted_entrypoint.validate_hosted_entrypoint(Settings())


@pytest.mark.parametrize("name,value,reason", [
    ("DEMO_ONLY_MODE", "false", "DEMO ONLY"),
    ("DATABASE_URL", "sqlite:///./unsafe.db", "PostgreSQL"),
    ("BACKEND_BASE_URL", "http://public.example.test", "HTTPS"),
    ("ADMIN_API_KEY", "weak", "ADMIN_API_KEY"),
])
def test_hosted_image_retains_app_startup_guards(monkeypatch, name, value, reason):
    _configured_hosted(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=reason):
        hosted_entrypoint.validate_hosted_entrypoint(Settings())


def test_hosted_image_accepts_valid_demo_config_without_server_side_effects(monkeypatch):
    _configured_hosted(monkeypatch)
    hosted_entrypoint.validate_hosted_entrypoint(Settings())


def test_hosted_entrypoint_never_execs_uvicorn_on_local_auth(monkeypatch):
    _configured_hosted(monkeypatch)
    monkeypatch.setenv("REQUIRE_LICENSE", "false")

    def forbidden_exec(*args):
        raise AssertionError("Uvicorn was executed before guard passed")

    monkeypatch.setattr(hosted_entrypoint.os, "execvp", forbidden_exec)
    with pytest.raises(SystemExit, match="requires REQUIRE_LICENSE=true"):
        hosted_entrypoint.main()


def test_hosted_entrypoint_preserves_uvicorn_cli_after_valid_preflight(monkeypatch):
    _configured_hosted(monkeypatch)
    calls = []
    monkeypatch.setattr(hosted_entrypoint.os, "execvp", lambda executable, argv: calls.append((executable, argv)))
    hosted_entrypoint.main()
    assert calls == [(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"],
    )]


def test_hosted_entrypoint_defaults_to_loopback_bind(monkeypatch):
    _configured_hosted(monkeypatch)
    monkeypatch.delenv("BACKEND_HOST", raising=False)
    calls = []
    monkeypatch.setattr(hosted_entrypoint.os, "execvp", lambda exe, argv: calls.append((exe, argv)))
    hosted_entrypoint.main()
    assert calls[0][1][3] == "127.0.0.1"
