"""Offline end-to-end output checks for the provider provisioning CLI.

These tests use fake HTTP responses, never provision an actual provider or
expose real credentials, and supplement the existing helper-level checks.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "provision_provider.py"
SPEC = importlib.util.spec_from_file_location("provision_provider_cli_output", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)

FAKE_KEY = "sgp_test_only_fake_provider_key"


class FakeResponse:
    status_code = 201

    def __init__(self, body: dict):
        self.body = body

    def json(self) -> dict:
        return self.body


class FakeClient:
    """In-memory admin API: record requests but never make HTTP calls."""

    def __init__(self, **kwargs):
        self.requests: list[tuple[str, dict]] = []
        self.options = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, path: str, json: dict) -> FakeResponse:
        self.requests.append((path, json))
        if path == "/admin/organizations":
            return FakeResponse({"id": "ORG-FAKE"})
        if path == "/admin/providers":
            return FakeResponse({"id": "PROVIDER-FAKE"})
        if path == "/admin/providers/PROVIDER-FAKE/credentials":
            return FakeResponse({
                "credential_id": "CRED-FAKE",
                "api_key": FAKE_KEY,
                "label": "initial-onboarding",
            })
        if path == "/admin/providers/PROVIDER-FAKE/feeds":
            return FakeResponse({"id": "FEED-FAKE", "paused": json["paused"]})
        raise AssertionError(f"unexpected synthetic admin route: {path}")


def args_for(*extra: str) -> list[str]:
    return [
        str(SCRIPT),
        "--backend", "http://127.0.0.1:8000",
        "--admin-id", "fake-admin",
        "--organization-name", "Fake Organisation",
        "--provider-name", "Fake Provider",
        *extra,
    ]


def test_file_delivery_emits_no_provider_key_on_stdout_or_stderr(
    monkeypatch, tmp_path, capsys,
):
    client = FakeClient()
    monkeypatch.setattr(provision.httpx, "Client", lambda **_kw: client)
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    target = tmp_path / "provider-key.json"
    monkeypatch.setattr(sys, "argv", args_for("--credential-output", str(target)))

    assert provision.main() == 0
    output = capsys.readouterr()
    assert FAKE_KEY not in (output.out + output.err)
    assert "provider_api_key" not in output.out
    receipt = json.loads(output.out)
    assert receipt["credential_id"] == "CRED-FAKE"
    assert receipt["credential_delivery"]["mode"] == "file"
    assert receipt["feed_paused"] is True
    assert json.loads(target.read_text(encoding="utf-8"))["provider_api_key"] == FAKE_KEY
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert client.requests[-1][1]["paused"] is True


def test_missing_delivery_method_refuses_before_any_admin_request(monkeypatch, capsys):
    def must_not_connect(**_kwargs):
        raise AssertionError("CLI contacted backend without safe credential delivery")

    monkeypatch.setattr(provision.httpx, "Client", must_not_connect)
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    monkeypatch.setattr(sys, "argv", args_for())

    with pytest.raises(SystemExit) as exc:
        provision.main()
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "choose credential delivery" in output.err
    assert FAKE_KEY not in (output.out + output.err)


def test_show_secret_is_explicit_opt_in_only(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(provision.httpx, "Client", lambda **_kw: client)
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    monkeypatch.setattr(sys, "argv", args_for("--show-secret"))

    assert provision.main() == 0
    output = capsys.readouterr()
    assert FAKE_KEY in output.out
    assert FAKE_KEY not in output.err
    assert len(client.requests) == 4


def test_environment_selected_file_and_show_secret_conflict_before_network(
    monkeypatch, tmp_path,
):
    def must_not_connect(**_kwargs):
        raise AssertionError("CLI contacted backend with conflicting delivery choices")

    monkeypatch.setattr(provision.httpx, "Client", must_not_connect)
    monkeypatch.setenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", str(tmp_path / "key.json"))
    monkeypatch.setattr(sys, "argv", args_for("--show-secret"))

    with pytest.raises(SystemExit) as exc:
        provision.main()
    assert exc.value.code == 2
    assert not (tmp_path / "key.json").exists()
