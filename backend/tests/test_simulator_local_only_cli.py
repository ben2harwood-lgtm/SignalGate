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
        sys, "argv",
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
        sys, "argv",
        [module.__name__ + ".py", *args, "--backend", "http://127.0.0.1:8000"],
    )
    with pytest.raises(SystemExit):
        module.main()
    assert client.paths == ["/health"]
    assert client.posts == []


# Documentation contracts for the corresponding synthetic-only operator guide.
_DEMO_SCRIPT = (
    Path(__file__).resolve().parents[2] / "docs" / "DEMO_SCRIPT.md"
).read_text(encoding="utf-8")


def test_demo_script_does_not_reuse_failed_frozen_rc2_for_broker_acceptance():
    assert "Use the frozen demo-only RC or a later explicitly named candidate" not in _DEMO_SCRIPT
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in _DEMO_SCRIPT
    assert "18 errors / 4 warnings" in _DEMO_SCRIPT
    assert "Do not use frozen RC2" in _DEMO_SCRIPT


def test_demo_script_keeps_simulator_broker_receipts_not_run():
    assert "internal, broker-free" in _DEMO_SCRIPT
    assert "NOT_RUN" in _DEMO_SCRIPT
    assert "synthetic only" in _DEMO_SCRIPT
    assert "Demo EA or simulator polls" not in _DEMO_SCRIPT


def test_demo_script_preserves_unmet_real_provider_pilot_entry_gates():
    assert "PR #60" in _DEMO_SCRIPT
    assert "regenerated EX5" in _DEMO_SCRIPT
    assert "actual MT5 demo-broker scenario receipts" in _DEMO_SCRIPT
    assert "docs/BETA_ACCEPTANCE.md" in _DEMO_SCRIPT
    assert "NOT STARTED" in _DEMO_SCRIPT
    assert "external feed must stay paused" in _DEMO_SCRIPT


class _SyntheticAckResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body

    def json(self):
        if self.body is None:
            raise ValueError("malformed acknowledgement JSON")
        return self.body


class _AckRefusalClient:
    def __init__(self, status_code, body):
        self.reply = _SyntheticAckResponse(status_code, body)
        self.posts = []

    def get(self, path, **_kwargs):
        assert path == "/commands/pending"
        return _SyntheticAckResponse(200, {"command": {
            "command_id": "SYNTHETIC-CMD", "symbol": "XAUUSD", "direction": "BUY"
        }})

    def post(self, path, **_kwargs):
        self.posts.append(path)
        if path == "/commands/SYNTHETIC-CMD/received":
            return self.reply
        raise AssertionError("simulator posted a fake fill after rejected acknowledgement")


@pytest.mark.parametrize("status_code,body", [
    (403, {"detail": "wrong owner"}),
    (409, {"detail": "command already terminal"}),
    (500, {"status": "received"}),
    (200, {"status": "unexpected"}),
    (200, []),
    (200, None),
])
def test_rejected_or_ambiguous_ack_cannot_emit_simulated_fills(status_code, body):
    """Broker-free command ACK must precede any fabricated execution/event."""
    stub = _AckRefusalClient(status_code, body)
    sim = ea_simulator.EASimulator(
        http=stub, user_id="SYNTHETIC-USER", api_key="test-local-only",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="acknowledgement was not accepted"):
        sim.run_once()
    assert stub.posts == ["/commands/SYNTHETIC-CMD/received"]
    assert "SYNTHETIC-CMD" not in sim.processed


class _LifecycleRefusalClient:
    def __init__(self, failing_stage, status_code, body):
        self.failing_stage = failing_stage
        self.failure = _SyntheticAckResponse(status_code, body)
        self.posts = []

    def post(self, path, **_kwargs):
        self.posts.append(path)
        if path.endswith("/execution"):
            return (self.failure if self.failing_stage == "execution"
                    else _SyntheticAckResponse(200, {"status": "ok"}))
        if path.endswith("/management_event"):
            return (self.failure if self.failing_stage == "management"
                    else _SyntheticAckResponse(200, {"status": "ok"}))
        raise AssertionError("unexpected synthetic HTTP write")


@pytest.mark.parametrize("stage,status_code,body", [
    ("execution", 403, {"detail": "wrong account"}),
    ("execution", 409, {"detail": "execution conflict"}),
    ("execution", 500, {"status": "ok"}),
    ("execution", 200, {"status": "duplicate_ignored"}),
    ("execution", 200, None),
    ("management", 403, {"detail": "wrong account"}),
    ("management", 409, {"detail": "event conflict"}),
    ("management", 500, {"status": "ok"}),
    ("management", 200, {"status": "duplicate_ignored"}),
    ("management", 200, None),
])
def test_rejected_synthetic_execution_or_event_halts_lifecycle(stage, status_code, body):
    """Synthetic management must stop after its first rejected backend write."""
    client = _LifecycleRefusalClient(stage, status_code, body)
    sim = ea_simulator.EASimulator(
        http=client, user_id="SYNTHETIC-USER", api_key="test-local-only",
        delay=0, verbose=False,
    )
    command = {
        "command_id": "SYNTHETIC-CMD", "symbol": "XAUUSD",
        "direction": "BUY", "entry_price": None,
        "initial_stop_loss": 2343.0, "lot_size": 0.01,
        "take_profits": [{"level": 1, "price": 2353.0, "lot": 0.01}],
    }
    label = "execution report" if stage == "execution" else "management event"
    with pytest.raises(RuntimeError, match=label + " was not accepted"):
        sim.simulate_lifecycle(command)
    expected = ["/commands/SYNTHETIC-CMD/execution"]
    if stage == "management":
        expected.append("/commands/SYNTHETIC-CMD/management_event")
    assert client.posts == expected
