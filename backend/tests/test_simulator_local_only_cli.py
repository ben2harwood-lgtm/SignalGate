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
            "command_id": "SYNTHETIC-CMD", "symbol": "XAUUSD", "direction": "BUY",
            "user_id": "SYNTHETIC-USER", "demo_only": True,
            "entry_type": "MARKET",
             "initial_stop_loss": 2343.0,
             "lot_size": 0.01,
             "take_profits": [{"level": 1, "price": 2353.0, "lot": 0.01}],
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


# A rejected/malformed scripted registration, signal, or approval must not
# cascade into another backend write or a synthetic execution receipt.
_SCRIPTED_PATHS = [
    "/register_user",
    "/signals/create",
    "/signals/LOCAL-SIGNAL/approve",
]
_SCRIPTED_SUCCESS = [
    {"id": "LOCAL-USER"},
    {"id": "LOCAL-SIGNAL", "parser_status": "VALID", "parser_error": None},
    {"result": "APPROVED", "command_id": "LOCAL-COMMAND"},
]


class _ScriptedFlowClient:
    def __init__(self, fail_step=None, status_code=200, body=None):
        self.fail_step = fail_step
        self.status_code = status_code
        self.body = body
        self.posts = []
        self.gets = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, path, **_kwargs):
        self.gets.append(path)
        assert path == "/health", "synthetic simulator polling not expected"
        return _SyntheticAckResponse(
            200, {"status": "ok", "demo_only_mode": True, "admin_paused": False}
        )

    def post(self, path, **_kwargs):
        self.posts.append(path)
        index = len(self.posts) - 1
        assert index < len(_SCRIPTED_PATHS), "unexpected synthetic write"
        assert path == _SCRIPTED_PATHS[index]
        if index == self.fail_step:
            return _SyntheticAckResponse(self.status_code, self.body)
        return _SyntheticAckResponse(200, _SCRIPTED_SUCCESS[index])


def _run_scripted_cli_with_stub(monkeypatch, client):
    def _stub_http_client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return client

    monkeypatch.setattr(run_demo_flow.httpx, "Client", _stub_http_client)
    monkeypatch.setattr(
        sys, "argv",
        ["run_demo_flow.py", "--admin-id", "LOCAL-ADMIN",
         "--backend", "http://127.0.0.1:8000"],
    )


@pytest.mark.parametrize("step", [0, 1, 2])
@pytest.mark.parametrize("response_kind", [
    "http403_success_shape",
    "http500_success_shape",
    "non_object_json",
    "invalid_json",
    "missing_identifier",
])
def test_scripted_flow_stops_at_unconfirmed_step(monkeypatch, step, response_kind):
    if response_kind == "http403_success_shape":
        status, body = 403, _SCRIPTED_SUCCESS[step]
    elif response_kind == "http500_success_shape":
        status, body = 500, _SCRIPTED_SUCCESS[step]
    elif response_kind == "non_object_json":
        status, body = 200, [_SCRIPTED_SUCCESS[step]]
    elif response_kind == "invalid_json":
        status, body = 200, None
    else:
        status, body = 200, (
            {"result": "APPROVED"} if step == 2 else {"parser_status": "VALID"}
        )
    client = _ScriptedFlowClient(step, status, body)
    _run_scripted_cli_with_stub(monkeypatch, client)
    with pytest.raises(RuntimeError, match="stopping synthetic flow"):
        run_demo_flow.main()
    assert client.gets == ["/health"]
    assert client.posts == _SCRIPTED_PATHS[:step + 1]


def test_scripted_flow_valid_receipts_reach_only_local_simulator(monkeypatch):
    client = _ScriptedFlowClient()
    _run_scripted_cli_with_stub(monkeypatch, client)
    invoked = []

    class _StubSimulator:
        def __init__(self, **kwargs):
            assert kwargs["http"] is client
            assert kwargs["user_id"] == "LOCAL-USER"
            invoked.append("created")

        def run_once(self, expected_command_id=None):
            assert expected_command_id == "LOCAL-COMMAND"
            invoked.append("ran")
            return True

    monkeypatch.setattr(run_demo_flow, "EASimulator", _StubSimulator)
    run_demo_flow.main()
    assert client.gets == ["/health"]
    assert client.posts == _SCRIPTED_PATHS
    assert invoked == ["created", "ran"]


class _DifferentPendingCommandClient:
    def __init__(self):
        self.paths = []
        self.posts = []

    def get(self, path, **_kwargs):
        self.paths.append(path)
        assert path == "/commands/pending"
        return _SyntheticAckResponse(200, {"command": {
            "command_id": "OLDER-COMMAND",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "user_id": "LOCAL-USER", "demo_only": True,
            "entry_type": "MARKET",
             "initial_stop_loss": 2343.0,
             "lot_size": 0.01,
             "take_profits": [{"level": 1, "price": 2353.0, "lot": 0.01}],
        }})

    def post(self, path, **_kwargs):
        self.posts.append(path)
        raise AssertionError("stale pending command was acknowledged or faked")


def test_expected_demo_command_mismatch_refuses_ack_or_fake_execution():
    stub = _DifferentPendingCommandClient()
    sim = ea_simulator.EASimulator(
        http=stub, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing synthetic execution"):
        sim.run_once(expected_command_id="NEWLY-APPROVED-COMMAND")
    assert stub.paths == ["/commands/pending"]
    assert stub.posts == []
    assert sim.processed == set()


def test_scripted_flow_rejects_stale_pending_command(monkeypatch):
    class _StaleQueue(_ScriptedFlowClient):
        def get(self, path, **kwargs):
            if path == "/commands/pending":
                self.gets.append(path)
                return _SyntheticAckResponse(200, {"command": {
                    "command_id": "OLDER-COMMAND",
                    "symbol": "XAUUSD",
                    "direction": "BUY",
                    "user_id": "LOCAL-USER", "demo_only": True,
            "entry_type": "MARKET",
             "initial_stop_loss": 2343.0,
             "lot_size": 0.01,
             "take_profits": [{"level": 1, "price": 2353.0, "lot": 0.01}],
                }})
            return super().get(path, **kwargs)

    client = _StaleQueue()
    _run_scripted_cli_with_stub(monkeypatch, client)
    with pytest.raises(RuntimeError, match="refusing synthetic execution"):
        run_demo_flow.main()
    assert client.gets == ["/health", "/commands/pending"]
    # Registration, creation and approval are the only three actions. No
    # acknowledgement or synthetic execution/management was sent.
    assert client.posts == _SCRIPTED_PATHS


class _UnconfirmedPollClient:
    def __init__(self, status_code, body):
        self.response = _SyntheticAckResponse(status_code, body)
        self.get_paths = []
        self.post_paths = []

    def get(self, path, **_kwargs):
        self.get_paths.append(path)
        assert path == "/commands/pending"
        return self.response

    def post(self, path, **_kwargs):
        self.post_paths.append(path)
        raise AssertionError("unconfirmed pending poll led to synthetic backend write")


_POLL_COMMAND = {
    "command_id": "LOCAL-ONLY-TEST-COMMAND",
    "symbol": "XAUUSD",
    "direction": "BUY",
    "user_id": "LOCAL-USER",
    "demo_only": True,
    "entry_type": "MARKET",
     "initial_stop_loss": 2343.0,
             "lot_size": 0.01,
     "take_profits": [{"level": 1, "price": 2353.0, "lot": 0.01}],
}


@pytest.mark.parametrize("http_status,body", [
    (403, {"command": _POLL_COMMAND}),
    (500, {"command": _POLL_COMMAND}),
    (302, {"command": _POLL_COMMAND}),
    (200, None),
    (200, []),
    (200, {}),
    (200, {"command": "unexpected"}),
    (200, {"command": {
        "command_id": "", "symbol": "XAUUSD", "direction": "BUY",
    }}),
])
def test_rejected_or_malformed_poll_cannot_ack_or_fake_execution(http_status, body):
    client = _UnconfirmedPollClient(http_status, body)
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        simulator.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert simulator.processed == set()


def test_confirmed_empty_poll_returns_without_ack_or_fake_execution():
    client = _UnconfirmedPollClient(200, {"command": None})
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert simulator.run_once() is False
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []


@pytest.mark.parametrize("command", [
    {**_POLL_COMMAND, "demo_only": False},
    {**_POLL_COMMAND, "demo_only": "true"},
    {key: value for key, value in _POLL_COMMAND.items() if key != "demo_only"},
    {**_POLL_COMMAND, "user_id": "OTHER-USER"},
    {key: value for key, value in _POLL_COMMAND.items() if key != "user_id"},
    {**_POLL_COMMAND, "direction": "CLOSE"},
    {**_POLL_COMMAND, "entry_type": "LIMIT"},
    {**_POLL_COMMAND, "entry_type": "market"},
    {key: value for key, value in _POLL_COMMAND.items() if key != "entry_type"},
])
def test_invalid_demo_command_is_not_acknowledged(command):
    """Wrong-owner, non-demo and unsupported-entry polls cannot fake fills."""
    client = _UnconfirmedPollClient(200, {"command": command})
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        simulator.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert simulator.processed == set()


@pytest.mark.parametrize("overrides", [
    {"initial_stop_loss": 0},
    {"initial_stop_loss": -1},
    {"initial_stop_loss": True},
    {"initial_stop_loss": float("nan")},
    {"take_profits": []},
    {"take_profits": "not-a-list"},
    {"take_profits": [{"level": 1, "price": 0}]},
    {"take_profits": [{"level": 1, "price": float("inf")}]},
    {"take_profits": [{"level": 2, "price": 2353.0}]},
])
def test_simulator_refuses_invalid_stop_or_tp1_before_ack(overrides):
    """The real EA refuses invalid SL/TP1; fake SUCCESS would be misleading."""
    command = {**_POLL_COMMAND, **overrides}
    client = _UnconfirmedPollClient(200, {"command": command})
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        simulator.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert simulator.processed == set()


@pytest.mark.parametrize("overrides", [
    {"lot_size": None},
    {"lot_size": 0},
    {"lot_size": float("nan")},
    {"lot_size": float("inf")},
    {"entry_price": -1},
    {"entry_price": float("inf")},
    {"take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 2, "price": None},
    ]},
    {"take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 2, "price": float("inf")},
    ]},
    {"take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 2, "price": 2358.0, "lot": float("nan")},
    ]},
    {"take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 1, "price": 2358.0},
    ]},
    {"take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 4, "price": 2363.0},
    ]},
    {"take_profits": [{"level": 1, "price": 2353.0}, None]},
    {"take_profits": [{"level": True, "price": 2353.0}]},
])
def test_malformed_extended_synthetic_command_values_refuse_ack(overrides):
    """Malformed later TPs and lot/entry prices cannot create fake fills."""
    command = {**_POLL_COMMAND, **overrides}
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        sim.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert sim.processed == set()


def test_complete_multi_target_synthetic_command_still_polls_read_only():
    command = {
        **_POLL_COMMAND,
        "lot_size": 0.03,
        "entry_price": 2349.0,
        "take_profits": [
            {"level": 1, "price": 2353.0, "lot": 0.01},
            {"level": 2, "price": 2358.0, "lot": None},
            {"level": 3, "price": 2363.0, "lot": 0.02},
        ],
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll() == command
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []


def test_owned_demo_pending_command_can_be_read_without_ack():
    client = _UnconfirmedPollClient(200, {"command": _POLL_COMMAND})
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert simulator.poll() == _POLL_COMMAND
    assert client.post_paths == []

@pytest.mark.parametrize("command_id", [
    "CMD/../received", "../CMD", "CMD?mode=1", "CMD#fragment",
    "CMD%2Fother", r"CMD\\other", "CMD with space", "CMD\nother",
    "CMD\x00other", "CMD-é", "C" * 129, ".hidden",
])
def test_poll_refuses_route_unsafe_command_ids_without_synthetic_writes(command_id):
    """Untrusted poll JSON must not select arbitrary ACK/report URL paths."""
    client = _UnconfirmedPollClient(
        200, {"command": {**_POLL_COMMAND, "command_id": command_id}}
    )
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        simulator.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert simulator.processed == set()


def test_poll_accepts_backend_generated_command_id_as_read_only():
    command = {**_POLL_COMMAND, "command_id": "CMD-0123456789ABCDEF"}
    client = _UnconfirmedPollClient(200, {"command": command})
    simulator = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert simulator.poll() == command
    assert client.post_paths == []

@pytest.mark.parametrize("step,field", [
    (0, "id"), (1, "id"), (2, "command_id"),
])
@pytest.mark.parametrize("bad_id", [
    "X/../Y", r"X\\Y", "X%2FY", "X\nY", "X\x00Y",
    "X Y", "X?Y", "X#Y", "X" * 129, "é", ".X",
])
def test_scripted_flow_rejects_unsafe_receipt_identifiers(monkeypatch, step, field, bad_id):
    """No subsequent synthetic write after a malformed issued identifier."""
    receipt = {**_SCRIPTED_SUCCESS[step], field: bad_id}
    client = _ScriptedFlowClient(fail_step=step, status_code=200, body=receipt)
    _run_scripted_cli_with_stub(monkeypatch, client)
    with pytest.raises(RuntimeError, match="valid identifier; stopping synthetic flow"):
        run_demo_flow.main()
    assert client.gets == ["/health"]
    assert client.posts == _SCRIPTED_PATHS[:step + 1]


@pytest.mark.parametrize("overrides", [
    {"initial_stop_loss": 2353.0},  # BUY SL == TP1
    {"initial_stop_loss": 2360.0},  # BUY SL above TP1
    {"direction": "SELL"},  # SELL stop below TP1
    {"direction": "SELL", "initial_stop_loss": 2353.0},  # equal
    {"take_profits": [
        {"level": 1, "price": 2353.0}, {"level": 2, "price": 2351.0},
    ]},  # BUY TP2 below TP1
    {"take_profits": [
        {"level": 1, "price": 2353.0}, {"level": 2, "price": 2353.0},
    ]},  # flat targets
    {"take_profits": [
        {"level": 1, "price": 2353.0}, {"level": 3, "price": 2350.0},
    ]},  # omitted TP2 does not permit inverted TP3
    {"entry_price": 2343.0},  # BUY entry equals SL
    {"entry_price": 2340.0},  # BUY entry below SL
    {"entry_price": 2353.0},  # BUY entry equals TP1
    {"entry_price": 2360.0},  # BUY entry above TP1
    {"direction": "SELL", "initial_stop_loss": 2363.0,
     "entry_price": 2363.0},  # SELL entry equals SL
    {"direction": "SELL", "initial_stop_loss": 2363.0,
     "entry_price": 2350.0},  # SELL entry below TP1
    {"direction": "SELL", "initial_stop_loss": 2363.0,
     "take_profits": [
         {"level": 1, "price": 2353.0}, {"level": 2, "price": 2355.0},
     ]},  # SELL TP2 must be lower than TP1
])
def test_inverted_price_geometry_never_acknowledges_or_fakes_fills(overrides):
    """The parser refuses direction-inconsistent SL/entry/targets."""
    command = {**_POLL_COMMAND, **overrides}
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        sim.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert sim.processed == set()


@pytest.mark.parametrize("command", [
    {**_POLL_COMMAND, "entry_price": 2348.0,
     "take_profits": [
         {"level": 1, "price": 2353.0},
         {"level": 2, "price": 2358.0},
         {"level": 3, "price": 2363.0},
     ]},
    {**_POLL_COMMAND, "direction": "SELL",
     "initial_stop_loss": 2363.0, "entry_price": 2358.0,
     "take_profits": [
         {"level": 1, "price": 2353.0},
         {"level": 2, "price": 2348.0},
         {"level": 3, "price": 2343.0},
     ]},
    {**_POLL_COMMAND, "take_profits": [
        {"level": 1, "price": 2353.0},
        {"level": 3, "price": 2363.0},
    ]},
])
def test_consistent_price_geometry_still_polls_without_ack(command):
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll() == command
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
