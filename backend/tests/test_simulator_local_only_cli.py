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



@pytest.mark.parametrize("flag,value", [
    ("--delay", "-0.01"),
    ("--delay", "nan"),
    ("--delay", "inf"),
    ("--delay", "-inf"),
    ("--poll-interval", "0"),
    ("--poll-interval", "-0.01"),
    ("--poll-interval", "nan"),
    ("--poll-interval", "inf"),
    ("--poll-interval", "-inf"),
])
def test_simulator_cli_refuses_invalid_timing_before_http(
    monkeypatch, flag, value,
):
    """Bad timing must not lead to ACK, synthetic writes or an infinite poll."""
    monkeypatch.setattr(
        sys, "argv",
        ["ea_simulator.py", "--user-id", "LOCAL-USER", "--once",
         "--backend", "http://127.0.0.1:8000", f"{flag}={value}"],
    )
    def _no_transport(*_args, **_kwargs):
        raise AssertionError("bad timing opened a client before refusal")
    monkeypatch.setattr(ea_simulator.httpx, "Client", _no_transport)
    with pytest.raises(SystemExit) as exc:
        ea_simulator.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("delay", [
    -0.1, float("nan"), float("inf"), -float("inf"), True, "0",
])
def test_programmatic_simulator_invalid_delay_is_refused_before_poll(delay):
    with pytest.raises(ValueError, match="delay must be finite"):
        ea_simulator.EASimulator(
            http=object(), user_id="LOCAL-USER", api_key="fake-test-key",
            delay=delay, verbose=False,
        )


@pytest.mark.parametrize("interval", [
    0, -1, float("nan"), float("inf"), True,
])
def test_programmatic_simulator_invalid_poll_interval_is_refused(interval):
    simulator = ea_simulator.EASimulator(
        http=object(), user_id="LOCAL-USER", api_key="fake-test-key",
        delay=0, verbose=False,
    )
    with pytest.raises(ValueError, match="poll interval must be finite"):
        simulator.run_forever(poll_interval=interval)


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
        "user_id": "SYNTHETIC-USER", "demo_only": True,
        "entry_type": "MARKET",
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



def test_scripted_flow_never_logs_unknown_health_fields(monkeypatch, capsys):
    """A permissive /health response must not leak extra fields to console."""
    canary = "CANARY_NOT_FOR_OPERATOR_LOGS"

    class _ExtendedHealthClient(_ScriptedFlowClient):
        def get(self, path, **_kwargs):
            self.gets.append(path)
            assert path == "/health"
            return _SyntheticAckResponse(200, {
                "status": "ok", "demo_only_mode": True, "admin_paused": False,
                "unrecognised_private_field": canary,
            })

    # Reject subsequent registration: no simulated command or fill occurs.
    client = _ExtendedHealthClient(fail_step=0, status_code=403, body={})
    _run_scripted_cli_with_stub(monkeypatch, client)
    with pytest.raises(RuntimeError, match="registration was not accepted"):
        run_demo_flow.main()
    captured = capsys.readouterr()
    assert canary not in captured.out + captured.err
    assert "Health: local demo-only backend confirmed (unpaused)" in captured.out
    assert client.gets == ["/health"]
    assert client.posts == ["/register_user"]




@pytest.mark.parametrize("status,accepted", [
    ("REJECTED", False),
    ("LEAK_ME_PARSER_STATUS", False),
    ("VALID", True),
])
def test_scripted_demo_never_logs_untrusted_parser_feedback(
    monkeypatch, capsys, status, accepted,
):
    """The backend parser receipt must not echo text or injected status to logs."""
    class _ParserReceiptClient(_ScriptedFlowClient):
        def post(self, path, **kwargs):
            if path == "/signals/create":
                self.posts.append(path)
                return _SyntheticAckResponse(200, {
                    "id": "LOCAL-SIGNAL",
                    "parser_status": status,
                    "parser_error": "PRIVATE_RAW_SIGNAL_CANARY",
                })
            return super().post(path, **kwargs)

    client = _ParserReceiptClient()
    _run_scripted_cli_with_stub(monkeypatch, client)

    class _NoNetworkSimulator:
        def __init__(self, **kwargs):
            assert kwargs["http"] is client

        def run_once(self, expected_command_id=None):
            assert expected_command_id == "LOCAL-COMMAND"
            return True

    monkeypatch.setattr(run_demo_flow, "EASimulator", _NoNetworkSimulator)
    if accepted:
        run_demo_flow.main()
    else:
        with pytest.raises(SystemExit) as exc:
            run_demo_flow.main()
        assert exc.value.code == 1

    output = capsys.readouterr()
    assert "PRIVATE_RAW_SIGNAL_CANARY" not in output.out + output.err
    assert "LEAK_ME_PARSER_STATUS" not in output.out + output.err
    assert client.posts == _SCRIPTED_PATHS[:3 if accepted else 2]
    assert ("(parser VALID)" in output.out) is accepted

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



@pytest.mark.parametrize("symbol", [
    "XAUUSD\\nPRIVATE-CANARY".replace("\\n", "\n"),
    "XAUUSD\\rPRIVATE-CANARY".replace("\\r", "\r"),
    "XAUUSD\\tJPY".replace("\\t", "\t"),
    "XAUUSD\\x1b[31m".replace("\\x1b", "\x1b"),
    "XAUUSD\\u200b".replace("\\u200b", "\u200b"),
    "XAUUSD JPY",
    " ",
    "X" * 129,
])
def test_simulator_refuses_malformed_symbol_before_ack(symbol):
    """Untrusted broker labels must not forge logs or fake fill receipts."""
    client = _UnconfirmedPollClient(
        200, {"command": {**_POLL_COMMAND, "symbol": symbol}}
    )
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="invalid command"):
        sim.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert sim.processed == set()


@pytest.mark.parametrize("symbol", ["XAUUSD", "XAUUSD.r", "BTCUSD#"])
def test_simulator_allows_printable_ascii_symbol_suffixes_on_poll(symbol):
    client = _UnconfirmedPollClient(
        200, {"command": {**_POLL_COMMAND, "symbol": symbol}}
    )
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll()["symbol"] == symbol
    assert client.post_paths == []


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

@pytest.mark.parametrize("targets", [
    [
        {"level": 2, "price": 2358.0, "lot": 0.02},
        {"level": 1, "price": 2353.0, "lot": 0.01},
    ],
    [
        {"level": 1, "price": 2353.0, "lot": 0.01},
        {"level": 3, "price": 2363.0, "lot": 0.03},
        {"level": 2, "price": 2358.0, "lot": 0.02},
    ],
])
def test_reordered_target_lots_cannot_fabricate_tp1_receipt(targets):
    """TP1_CLOSE must never use a preceding TP2/TP3 stage's lot value."""
    client = _UnconfirmedPollClient(
        200, {"command": {**_POLL_COMMAND, "take_profits": targets}}
    )
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="refusing fake execution"):
        sim.run_once()
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []
    assert sim.processed == set()

@pytest.mark.parametrize("direction,stop,tp1", [
    ("BUY", 1.080001, 1.080002),
    ("SELL", 1.080002, 1.080001),
])
def test_narrow_valid_market_bracket_keeps_implied_entry_inside(direction, stop, tp1):
    """Fake MARKET entries must not round outside otherwise valid SL/TP1."""
    command = {
        **_POLL_COMMAND,
        "direction": direction,
        "initial_stop_loss": stop,
        "take_profits": [{"level": 1, "price": tp1, "lot": 0.01}],
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll() == command
    fake_entry = ea_simulator._implied_entry(command)
    assert min(stop, tp1) < fake_entry < max(stop, tp1)
    assert client.post_paths == []


def test_unrepresentable_market_bracket_refuses_before_fake_ack():
    """Adjacent floating prices cannot support a truthful synthetic entry."""
    command = {
        **_POLL_COMMAND,
        "initial_stop_loss": 1.0,
        "take_profits": [
            {"level": 1, "price": float.fromhex("0x1.0000000000001p+0"), "lot": 0.01}
        ],
    }
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


@pytest.mark.parametrize("invalid_split_mode", [
    "false", "true", 0, 1, None, [], {},
])
def test_non_boolean_split_mode_refuses_before_fake_ack(invalid_split_mode):
    """Malformed split-mode types must not choose synthetic child-ticket count."""
    command = {**_POLL_COMMAND, "split_ticket_demo_partial_mode": invalid_split_mode}
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


@pytest.mark.parametrize("split_mode", [False, True])
def test_boolean_split_mode_can_poll_without_fake_writes(split_mode):
    """Real CommandOut emits a bool; do not reject valid split-mode values."""
    command = {**_POLL_COMMAND, "split_ticket_demo_partial_mode": split_mode}
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll() == command
    assert client.get_paths == ["/commands/pending"]
    assert client.post_paths == []


@pytest.mark.parametrize("levels,expected_stage", [
    ([1, 3], "TP1_DONE"),
    ([1, 2, 3], "TP2_DONE"),
])
def test_tp3_reached_preserves_actual_prior_synthetic_stage(
    monkeypatch, levels, expected_stage,
):
    """No fake TP2_DONE milestone when the valid parser skips TP2."""
    command = {
        **_POLL_COMMAND,
        "lot_size": 0.01 * len(levels),
        "split_ticket_demo_partial_mode": True,
        "take_profits": [
            {"level": level, "price": 2353.0 + 5 * (level - 1), "lot": 0.01}
            for level in levels
        ],
    }
    sim = ea_simulator.EASimulator(
        http=None, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    evidence = []
    monkeypatch.setattr(sim, "post_execution", lambda *_args: None)
    monkeypatch.setattr(
        sim, "post_event",
        lambda _command_id, **fields: evidence.append(fields),
    )
    sim.simulate_lifecycle(command)
    stage = next(
        ev["stage"] for ev in evidence if ev["event_type"] == "TP3_REACHED"
    )
    assert stage == expected_stage
    assert any(ev["event_type"] == "TP1_CLOSE_SUCCESS" for ev in evidence)
    assert (
        any(ev["event_type"] == "TP2_CLOSE_SUCCESS" for ev in evidence)
        == (2 in levels)
    )
    assert evidence[-1]["event_type"] == "FULLY_CLOSED"


@pytest.mark.parametrize("levels", [[1], [1, 2], [1, 2, 3]])
def test_split_mode_creates_only_configured_stage_children(monkeypatch, levels):
    """Synthetic FULLY_CLOSED cannot imply closure of phantom child tickets."""
    targets = [
        {"level": level, "price": 2353.0 + 5.0 * (level - 1), "lot": 0.01}
        for level in levels
    ]
    command = {
        **_POLL_COMMAND,
        "take_profits": targets,
        "split_ticket_demo_partial_mode": True,
    }
    sim = ea_simulator.EASimulator(
        http=None, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    evidence = {"events": []}

    def record_execution(_command, tickets):
        evidence["children"] = tickets

    def record_event(_command_id, **fields):
        evidence["events"].append(fields)

    monkeypatch.setattr(sim, "post_execution", record_execution)
    monkeypatch.setattr(sim, "post_event", record_event)
    sim.simulate_lifecycle(command)
    children = evidence["children"]
    closed = [ev["broker_ticket"] for ev in evidence["events"]
              if ev["event_type"] in {
                  "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS"
              }]
    assert len(children) == len(levels)
    assert closed == children
    assert evidence["events"][-1]["event_type"] == "FULLY_CLOSED"

@pytest.mark.parametrize("levels", [[1, 2], [1, 2, 3]])
@pytest.mark.parametrize("direct_call", [False, True])
def test_split_multi_child_stop_out_refuses_synthetic_closure_before_writes(
    levels, direct_call,
):
    """One synthetic child STOP_LOSS_HIT cannot close several reported children."""
    targets = [
        {"level": level, "price": 2353.0 + 5.0 * (level - 1), "lot": 0.01}
        for level in levels
    ]
    command = {
        **_POLL_COMMAND,
        "lot_size": 0.01 * len(levels),
        "take_profits": targets,
        "split_ticket_demo_partial_mode": True,
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False, scenario="stop_out",
    )
    with pytest.raises(RuntimeError, match="cannot prove every child closed"):
        if direct_call:
            sim.simulate_lifecycle(command)
        else:
            sim.run_once()
    assert client.get_paths == ([] if direct_call else ["/commands/pending"])
    assert client.post_paths == []
    assert sim.processed == set()




@pytest.mark.parametrize("levels", [[1], [1, 2, 3]])
def test_synthetic_tickets_never_reuse_fixed_identity_across_commands_or_users(
    monkeypatch, levels,
):
    """Fake identities are stable for a retry, but isolated by user and command."""
    command = {
        **_POLL_COMMAND,
        "take_profits": [
            {"level": level, "price": 2353.0 + 5 * (level - 1), "lot": 0.01}
            for level in levels
        ],
        "lot_size": 0.01 * len(levels),
        "split_ticket_demo_partial_mode": True,
    }
    captured = []

    def collect(user_id, command_id):
        sim = ea_simulator.EASimulator(
            http=None, user_id=user_id, api_key="synthetic-key",
            delay=0, verbose=False,
        )
        monkeypatch.setattr(
            sim, "post_execution",
            lambda _command, tickets: captured.append(tuple(tickets)),
        )
        monkeypatch.setattr(sim, "post_event", lambda *_a, **_kw: None)
        sim.simulate_lifecycle({
            **command, "command_id": command_id, "user_id": user_id,
        })

    collect("LOCAL-USER", "CMD-ONE")
    collect("LOCAL-USER", "CMD-TWO")
    collect("OTHER-USER", "CMD-ONE")
    collect("LOCAL-USER", "CMD-ONE")
    assert captured[0] == captured[3]
    assert len({tuple(tickets) for tickets in captured[:3]}) == 3
    assert all(len(tickets) == len(levels) for tickets in captured)
    assert all(len(set(tickets)) == len(tickets) for tickets in captured)
    assert all(ticket.isascii() and ticket.isdigit()
               for tickets in captured for ticket in tickets)

@pytest.mark.parametrize("split_mode,levels", [
    (True, [1]), (False, [1, 2, 3]),
])
def test_one_ticket_stop_out_remains_broker_free_and_synthetic(
    monkeypatch, split_mode, levels,
):
    """A single simulated ticket still emits exactly one stop-out closure."""
    command = {
        **_POLL_COMMAND,
        "lot_size": 0.01 * len(levels),
        "take_profits": [
            {"level": level, "price": 2353.0 + 5.0 * (level - 1), "lot": 0.01}
            for level in levels
        ],
        "split_ticket_demo_partial_mode": split_mode,
    }
    sim = ea_simulator.EASimulator(
        http=None, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False, scenario="stop_out",
    )
    evidence = {"events": []}
    monkeypatch.setattr(
        sim, "post_execution",
        lambda _command, tickets: evidence.update(children=tickets),
    )
    monkeypatch.setattr(
        sim, "post_event",
        lambda _command_id, **fields: evidence["events"].append(fields),
    )
    sim.simulate_lifecycle(command)
    assert evidence["children"] == [
        ea_simulator._fake_ticket(
            ea_simulator._synthetic_ticket_base("LOCAL-USER", command["command_id"]), 0
        )
    ]
    assert [event["event_type"] for event in evidence["events"]] == [
        "OPENED", "STOP_LOSS_HIT", "FULLY_CLOSED",
    ]
    assert evidence["events"][1]["broker_ticket"] == evidence["children"][0]


@pytest.mark.parametrize("levels,split_mode,expected_stop_moves", [
    ((1,), False, ()),
    ((1,), True, ()),
    ((1, 2), True, ("SL_MOVE_BREAKEVEN_SUCCESS",)),
    ((1, 3), True, ("SL_MOVE_BREAKEVEN_SUCCESS",)),
    ((1, 2, 3), True, ("SL_MOVE_BREAKEVEN_SUCCESS", "SL_MOVE_TP1_SUCCESS")),
])
def test_synthetic_win_does_not_report_stop_move_after_last_child_closes(
    monkeypatch, levels, split_mode, expected_stop_moves,
):
    """A closed synthetic position cannot acknowledge a later stop amendment."""
    command = {
        **_POLL_COMMAND,
        "lot_size": len(levels) * 0.01,
        "split_ticket_demo_partial_mode": split_mode,
        "take_profits": [
            {"level": level, "price": 2353.0 + 5 * (level - 1), "lot": 0.01}
            for level in levels
        ],
    }
    sim = ea_simulator.EASimulator(
        http=None, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    events = []
    monkeypatch.setattr(sim, "post_execution", lambda *_args: None)
    monkeypatch.setattr(
        sim, "post_event",
        lambda _command_id, **fields: events.append(fields),
    )
    sim.simulate_lifecycle(command)
    moves = tuple(
        event["event_type"] for event in events
        if event["event_type"].startswith("SL_MOVE_")
    )
    closures = [
        event for event in events
        if event["event_type"] in {
            "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS",
        }
    ]
    assert moves == expected_stop_moves
    assert len(closures) == len(levels)
    assert events[-1]["event_type"] == "FULLY_CLOSED"


@pytest.mark.parametrize("split_mode,expected_lots", [
    (False, 0.05),
    (True, 0.06),
    (None, 0.05),  # Legacy synthetic command with absent split flag.
])
def test_synthetic_reported_fill_volume_matches_ticket_mode(
    split_mode, expected_lots,
):
    """One fake position must not inherit the sum of split child quantities."""
    class _CaptureExecution:
        def __init__(self):
            self.writes = []

        def post(self, path, **kwargs):
            self.writes.append((path, kwargs["json"]))
            return _SyntheticAckResponse(200, {"status": "ok"})

    command = {
        **_POLL_COMMAND,
        "lot_size": 0.05,
        "take_profits": [
            {"level": 1, "price": 2353.0, "lot": 0.02},
            {"level": 2, "price": 2358.0, "lot": 0.04},
        ],
    }
    if split_mode is not None:
        command["split_ticket_demo_partial_mode"] = split_mode
    client = _CaptureExecution()
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    child_tickets = (
        ["FAKE-TICKET-1", "FAKE-TICKET-2"]
        if split_mode is True else ["FAKE-TICKET-1"]
    )
    sim.post_execution(command, child_tickets)
    assert len(client.writes) == 1
    path, receipt = client.writes[0]
    assert path == "/commands/LOCAL-ONLY-TEST-COMMAND/execution"
    assert receipt["status"] == "SUCCESS"
    assert receipt["lot_size"] == pytest.approx(expected_lots)


@pytest.mark.parametrize("targets", [
    [{"level": 1, "price": 2353.0}],  # Child size omitted.
    [{"level": 1, "price": 2353.0, "lot": None}],
    [
        {"level": 1, "price": 2353.0, "lot": 0.01},
        {"level": 2, "price": 2358.0},  # Only the second child is unquantified.
    ],
])
@pytest.mark.parametrize("entrypoint", ["run_once", "simulate_lifecycle", "post_execution"])
def test_split_children_without_explicit_lots_cannot_fabricate_execution(
    targets, entrypoint,
):
    """Missing split-child volume must fail before any fake ACK/fill/event."""
    command = {
        **_POLL_COMMAND,
        "split_ticket_demo_partial_mode": True,
        "take_profits": targets,
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match=(
        "invalid command" if entrypoint == "run_once" else
        "lack positive explicit lots"
    )):
        if entrypoint == "run_once":
            sim.run_once()
        elif entrypoint == "simulate_lifecycle":
            sim.simulate_lifecycle(command)
        else:
            sim.post_execution(command, ["SYNTHETIC-TICKET"])
    assert client.get_paths == (["/commands/pending"] if entrypoint == "run_once" else [])
    assert client.post_paths == []
    assert sim.processed == set()


def test_complete_split_child_lots_can_still_poll_without_writes():
    command = {
        **_POLL_COMMAND,
        "split_ticket_demo_partial_mode": True,
        "take_profits": [
            {"level": 1, "price": 2353.0, "lot": 0.02},
            {"level": 2, "price": 2358.0, "lot": 0.01},
        ],
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    assert sim.poll() == command
    assert client.post_paths == []


@pytest.mark.parametrize("bad_flag", [
    "false", "true", None, 0, 1, [], {},
])
@pytest.mark.parametrize("entrypoint", ["simulate_lifecycle", "post_execution"])
def test_direct_synthetic_calls_refuse_nonboolean_split_flag_before_writes(
    bad_flag, entrypoint,
):
    """A truthy string 'false' must never create phantom fake child tickets."""
    command = {
        **_POLL_COMMAND,
        "split_ticket_demo_partial_mode": bad_flag,
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="mode must be boolean"):
        if entrypoint == "simulate_lifecycle":
            sim.simulate_lifecycle(command)
        else:
            sim.post_execution(command, ["SYNTHETIC-TICKET"])
    assert client.get_paths == []
    assert client.post_paths == []
    assert sim.processed == set()


@pytest.mark.parametrize("overrides", [
    {"demo_only": False},
    {"demo_only": "true"},
    {"user_id": "OTHER-USER"},
    {"entry_type": "LIMIT"},
    {"direction": "CLOSE"},
    {"symbol": "XAUUSD\\nUNTRUSTED".replace("\\n", "\n")},
    {"initial_stop_loss": 2400.0},
    {"take_profits": [
        {"level": 1, "price": 2353.0, "lot": 0.01},
        {"level": 2, "price": 2353.0, "lot": 0.01},
    ]},
    {"command_id": "BAD/ROUTE"},
    {"entry_price": float("inf")},
])
@pytest.mark.parametrize("entrypoint", ["simulate_lifecycle", "post_execution"])
def test_direct_synthetic_writers_apply_full_poll_guard_before_any_write(
    overrides, entrypoint,
):
    """In-process callers cannot skip demo/owner/price/route validation."""
    command = {**_POLL_COMMAND, **overrides}
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="direct-call preflight"):
        if entrypoint == "simulate_lifecycle":
            sim.simulate_lifecycle(command)
        else:
            sim.post_execution(command, ["SYNTHETIC-TICKET"])
    assert client.get_paths == []
    assert client.post_paths == []
    assert sim.processed == set()


@pytest.mark.parametrize("split_mode,child_tickets", [
    (False, []),                          # SUCCESS without any fake ticket
    (False, ["FAKE-1", "FAKE-2"]),        # Phantom extra single-position child
    (True, []),                           # Missing both split children
    (True, ["FAKE-1"]),                   # Missing second split child
    (True, ["FAKE-1", "FAKE-2", "FAKE-3"]),  # Phantom extra split child
    (True, ["FAKE-1", "FAKE-1"]),         # Same child counted twice
    (False, ["BAD/ROUTE"]),              # Fake ticket cannot be a URL path
    (False, ["BAD\\nLOG".replace("\\n", "\n")]),  # Receipt/log injection
    (False, ["X" * 129]),                # Unbounded identifier
    (False, [1]),                        # Non-string identity
    (True, ["FAKE-1", None]),            # Malformed second child
    (False, "FAKE-1"),                   # Not a list of tickets
    (False, None),                       # Missing identity collection
])
def test_direct_synthetic_execution_refuses_false_child_ticket_identities(
    split_mode, child_tickets,
):
    """Bad in-process child lists cannot create synthetic SUCCESS receipts."""
    command = {
        **_POLL_COMMAND,
        "split_ticket_demo_partial_mode": split_mode,
        "lot_size": 0.02,
        "take_profits": [
            {"level": 1, "price": 2353.0, "lot": 0.01},
            {"level": 2, "price": 2358.0, "lot": 0.01},
        ],
    }
    client = _UnconfirmedPollClient(200, {"command": command})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="child-ticket identities inconsistent"):
        sim.post_execution(command, child_tickets)
    assert client.post_paths == []
    assert client.get_paths == []
    assert sim.processed == set()


@pytest.mark.parametrize("bad_id", [
    "", "CMD/../admin", "CMD%2Fother", "CMD?redirect=1",
    "CMD#fragment", "CMD\\nFORGED".replace("\\n", "\n"),
    "X" * 129, None, 123,
])
@pytest.mark.parametrize("entrypoint", ["ack_received", "post_event"])
def test_direct_synthetic_callbacks_reject_unsafe_id_before_any_write(
    bad_id, entrypoint,
):
    """No direct ACK or fake management callback may escape its command route."""
    client = _UnconfirmedPollClient(200, {"command": _POLL_COMMAND})
    sim = ea_simulator.EASimulator(
        http=client, user_id="LOCAL-USER", api_key="synthetic-key",
        delay=0, verbose=False,
    )
    with pytest.raises(RuntimeError, match="invalid command ID"):
        if entrypoint == "ack_received":
            sim.ack_received(bad_id)
        else:
            sim.post_event(
                bad_id, event_type="OPENED", stage="OPENED", result="SUCCESS"
            )
    assert client.post_paths == []
    assert client.get_paths == []
    assert sim.processed == set()
