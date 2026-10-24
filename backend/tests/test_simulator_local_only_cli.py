"""Synthetic EA/demo CLI writers must never address public backend origins."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

# Match the pre-existing simulator test import path, without a network call.
_SIM = str(Path(__file__).resolve().parents[2] / "simulator")
if _SIM not in sys.path:
    sys.path.insert(0, _SIM)

import ea_simulator  # noqa: E402
import run_demo_flow  # noqa: E402


@pytest.mark.parametrize("origin", [
    "https://example.com", "http://example.com",
    "http://localhost:8000", "http://localhost.evil.com:8000",
    "http://192.168.1.2:8000", "http://127.0.0.2:8000",
    "http://0.0.0.0:8000", "http://[::2]:8000",
    "http://user:pass@127.0.0.1:8000",
    "http://127.0.0.1:8000/path",
    "http://127.0.0.1:8000?key=1",
    "http://127.0.0.1:8000#fragment",
    "http://127.0.0.1:0", "http://127.0.0.1:",
    "http://127.0.0.1:99999", "http://127.0.0.1\nev.il",
    "//127.0.0.1:8000", "127.0.0.1:8000",
])
def test_unsafe_origin_refused_before_transport(origin):
    with pytest.raises(ValueError):
        ea_simulator.validate_local_backend_origin(origin)


@pytest.mark.parametrize("origin,expected", [
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("http://[::1]:8000/", "http://[::1]:8000"),
    ("http://127.0.0.1", "http://127.0.0.1"),
])
def test_explicit_numeric_loopback_origin_allowed(origin, expected):
    assert ea_simulator.validate_local_backend_origin(origin) == expected


@pytest.mark.parametrize("module,args", [
    (ea_simulator, ["--user-id", "USER-LOCAL"]),
    (run_demo_flow, ["--admin-id", "LOCAL-ADMIN"]),
])
def test_cli_rejects_remote_origin_without_opening_client(
    monkeypatch, module, args
):
    monkeypatch.setattr(
        module.sys, "argv",
        [module.__name__ + ".py", *args, "--backend", "https://remote.example"],
    )
    def _no_transport(*_args, **_kwargs):
        raise AssertionError("unsafe origin reached the HTTP client")
    monkeypatch.setattr(module.httpx, "Client", _no_transport)
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


class _HealthOnly:
    def __init__(self, data, *, status_code=200):
        self.data = data
        self.status_code = status_code
        self.paths = []
        self.posts = []
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def get(self, path, **_kwargs):
        self.paths.append(path)
        assert path == "/health", "no polling before health preflight"
        return self
    def json(self):
        return self.data
    def post(self, *_args, **_kwargs):
        self.posts.append(1)
        raise AssertionError("no write before health preflight")


@pytest.mark.parametrize("module,args", [
    (ea_simulator, ["--user-id", "USER-LOCAL", "--once"]),
    (run_demo_flow, ["--admin-id", "LOCAL-ADMIN"]),
])
@pytest.mark.parametrize("health", [
    {"status": "ok", "demo_only_mode": False, "admin_paused": False},
    {"status": "ok", "demo_only_mode": True, "admin_paused": True},
    {"status": "ok", "demo_only_mode": True},  # unknown pause is fail-closed
    {"status": "unavailable", "demo_only_mode": True, "admin_paused": False},
    [],
])
def test_cli_rejects_bad_health_before_poll_or_write(
    monkeypatch, module, args, health
):
    client = _HealthOnly(health)
    def _client(*_args, **kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return client
    monkeypatch.setattr(module.httpx, "Client", _client)
    monkeypatch.setattr(
        module.sys, "argv",
        [module.__name__ + ".py", *args, "--backend", "http://127.0.0.1:8000"],
    )
    with pytest.raises(SystemExit):
        module.main()
    assert client.paths == ["/health"]
    assert client.posts == []
