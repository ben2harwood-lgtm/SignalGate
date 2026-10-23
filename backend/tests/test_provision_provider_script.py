"""Provider provisioning CLI safety tests."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "provision_provider.py"
SPEC = importlib.util.spec_from_file_location("provision_provider", SCRIPT)
assert SPEC and SPEC.loader
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


def test_provider_provisioning_feed_payload_starts_paused():
    payload = provision.feed_create_payload("Main Feed", "provider-main")
    assert payload == {
        "name": "Main Feed",
        "source_namespace": "provider-main",
        "paused": True,
    }



def _provider():
    return {"id": "PROVIDER-1"}


def _credential():
    return {
        "credential_id": "PCRED-1",
        "api_key": "sgp_once_only_secret",
        "label": "initial-onboarding",
    }


def test_secret_record_contains_one_time_key_but_public_receipt_does_not(tmp_path):
    provider = _provider()
    credential = _credential()
    secret = provision.credential_secret_record(provider, credential)
    assert secret["provider_api_key"] == credential["api_key"]

    receipt = provision.public_receipt(
        backend="https://api.example.test",
        org={"id": "ORG-1"},
        provider=provider,
        credential=credential,
        feed={"id": "FEED-1", "paused": True},
        delivery_mode="file",
        credential_output=tmp_path / "provider-secret.json",
    )
    encoded = json.dumps(receipt)
    assert credential["api_key"] not in encoded
    assert "provider_api_key" not in receipt
    assert receipt["credential_id"] == credential["credential_id"]
    assert receipt["feed_paused"] is True


def test_credential_output_refuses_existing_file(tmp_path):
    target = tmp_path / "provider-secret.json"
    target.write_text("existing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        provision.validate_credential_output(str(target))


def test_credential_output_requires_existing_parent(tmp_path):
    target = tmp_path / "missing" / "provider-secret.json"
    with pytest.raises(ValueError, match="parent does not exist"):
        provision.validate_credential_output(str(target))


def test_write_credential_secret_never_overwrites_and_is_owner_only(tmp_path):
    target = tmp_path / "provider-secret.json"
    record = provision.credential_secret_record(_provider(), _credential())

    provision.write_credential_secret(target, record)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["provider_api_key"] == _credential()["api_key"]

    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    with pytest.raises(FileExistsError):
        provision.write_credential_secret(target, record)


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000/",
        "http://[::1]:8000/",
        "https://provider.example.invalid",
        "https://provider.example.invalid:8443/",
    ],
)
def test_admin_provisioning_allows_loopback_http_or_remote_https(origin):
    assert provision.validate_admin_backend_url(origin) == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    [
        "http://provider.example.invalid",
        "http://127.0.0.1.attacker.invalid",
        "http://192.168.0.12:8000",
        "http://[::]:8000",
        "ftp://provider.example.invalid",
        "https://user:fake-password@provider.example.invalid",
        "https://provider.example.invalid/admin",
        "https://provider.example.invalid?credential=FAKE",
        "https://provider.example.invalid/#fragment",
        "https://provider.example.invalid:INVALID",
        "https://provider.example.invalid\\\\@attacker.invalid",
        " https://provider.example.invalid",
        "",
        "not-an-origin",
    ],
)
def test_admin_provisioning_invalid_origins_fail_before_any_network(
    origin, monkeypatch, tmp_path, capsys
):
    """No admin mutation or credential delivery is attempted for unsafe origins."""
    import sys

    calls = []
    def unexpected_client(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Admin API connection must not be constructed")

    monkeypatch.setattr(provision.httpx, "Client", unexpected_client)
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    target = tmp_path / "never-created-secret.json"
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT),
        "--backend", origin,
        "--admin-id", "FAKE-ADMIN",
        "--organization-name", "Fictional Organisation",
        "--provider-name", "Fictional Provider",
        "--credential-output", str(target),
    ])

    with pytest.raises(SystemExit) as exc:
        provision.main()
    assert exc.value.code == 2
    assert calls == []
    assert not target.exists()
    captured = capsys.readouterr()
    assert "FAKE" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
