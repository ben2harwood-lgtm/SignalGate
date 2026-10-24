"""The optional Python convenience runner is not a public/hosted entrypoint."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_backend


@pytest.fixture
def local_settings():
    return SimpleNamespace(
        demo_only_mode=True,
        require_license=False,
        database_url="sqlite:///./local-demo.db",
        backend_host="127.0.0.1",
        backend_port=8000,
        validate_startup=lambda: None,
    )


def _must_not_start_uvicorn(monkeypatch, local_settings) -> None:
    monkeypatch.setattr(run_backend, "get_settings", lambda: local_settings)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe configuration reached Uvicorn")
    monkeypatch.setattr(run_backend.uvicorn, "run", forbidden)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.4", "localhost", ""])
def test_refuses_non_numeric_loopback_bind(monkeypatch, local_settings, host):
    local_settings.backend_host = host
    _must_not_start_uvicorn(monkeypatch, local_settings)
    with pytest.raises(RuntimeError, match="loopback"):
        run_backend.main()


@pytest.mark.parametrize("database_url", [
    "postgresql://u:p@localhost/demo", "postgres://u:p@localhost/demo",
    "mysql://u:p@localhost/demo",
])
def test_refuses_local_header_mode_with_non_sqlite_database(
    monkeypatch, local_settings, database_url
):
    local_settings.database_url = database_url
    _must_not_start_uvicorn(monkeypatch, local_settings)
    with pytest.raises(RuntimeError, match="SQLite"):
        run_backend.main()


def test_refuses_hosted_mode_in_reload_launcher(monkeypatch, local_settings):
    local_settings.require_license = True
    _must_not_start_uvicorn(monkeypatch, local_settings)
    with pytest.raises(RuntimeError, match="local-only"):
        run_backend.main()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_allows_local_sqlite_only_without_network(monkeypatch, local_settings, host):
    local_settings.backend_host = host
    monkeypatch.setattr(run_backend, "get_settings", lambda: local_settings)
    calls = []
    monkeypatch.setattr(run_backend.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    run_backend.main()
    assert calls == [(("app.main:app",), {"host": host, "port": 8000, "reload": True})]
