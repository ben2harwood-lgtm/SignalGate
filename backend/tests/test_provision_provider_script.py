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


def _run_provisioning_mocked(monkeypatch, capsys, tmp_path, respond):
    """Exercise CLI using isolated synthetic HTTP; never reach a real API."""
    import sys
    import httpx

    calls = []
    target = tmp_path / "synthetic-credential.json"
    original_client = provision.httpx.Client

    def handle(request):
        calls.append(request.url.path)
        return respond(request)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            provision.httpx, "Client",
            lambda **kwargs: original_client(
                **kwargs, transport=httpx.MockTransport(handle)
            ),
        )
        patcher.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
        patcher.setattr(sys, "argv", [
            str(SCRIPT),
            "--backend", "https://provision.example.invalid",
            "--admin-id", "SYNTHETIC-ADMIN",
            "--organization-name", "Fictional Organisation",
            "--provider-name", "Fictional Provider",
            "--credential-output", str(target),
        ])
        with pytest.raises(SystemExit) as error:
            provision.main()
    return error.value.code, capsys.readouterr(), calls, target


@pytest.mark.parametrize("status", [302, 403, 500])
def test_provisioning_error_body_is_never_printed(
    monkeypatch, capsys, tmp_path, status
):
    import httpx

    secret = "SYNTHETIC-ADMIN-ERROR-SECRET"

    def respond(request):
        return httpx.Response(status, text=f"private failure: {secret}")

    code, captured, calls, target = _run_provisioning_mocked(
        monkeypatch, capsys, tmp_path, respond
    )
    assert code == 1
    assert calls == ["/admin/organizations"]
    assert not target.exists()
    assert secret not in captured.out + captured.err
    assert str(status) in captured.err
    assert "inspect tenant state" in captured.err.lower()


def test_provisioning_transport_exception_is_not_printed(
    monkeypatch, capsys, tmp_path
):
    import httpx

    secret = "SYNTHETIC-TRANSPORT-EXCEPTION-SECRET"

    def respond(request):
        raise httpx.ConnectError(f"remote token={secret}", request=request)

    code, captured, calls, target = _run_provisioning_mocked(
        monkeypatch, capsys, tmp_path, respond
    )
    assert code == 1
    assert calls == ["/admin/organizations"]
    assert not target.exists()
    assert secret not in captured.out + captured.err
    assert "ConnectError" in captured.err
    assert "inspect tenant state" in captured.err.lower()


@pytest.mark.parametrize("shape", ["invalid-json", "unexpected-list"])
def test_provisioning_invalid_success_body_fails_closed_without_echo(
    monkeypatch, capsys, tmp_path, shape
):
    import httpx

    secret = "SYNTHETIC-MALFORMED-RESPONSE-SECRET"

    def respond(request):
        if shape == "invalid-json":
            return httpx.Response(200, text=f"<private>{secret}</private>")
        return httpx.Response(200, json=[secret])

    code, captured, calls, target = _run_provisioning_mocked(
        monkeypatch, capsys, tmp_path, respond
    )
    assert code == 1
    assert calls == ["/admin/organizations"]
    assert not target.exists()
    assert secret not in captured.out + captured.err
    assert "inspect tenant state" in captured.err.lower()


def test_feed_failure_after_credential_issuance_does_not_leak_secret(
    monkeypatch, capsys, tmp_path
):
    import httpx

    api_secret = "SYNTHETIC-ISSUED-PROVIDER-KEY"
    error_secret = "SYNTHETIC-SECRET-IN-FEED-ERROR"
    expected = [
        "/admin/organizations",
        "/admin/providers",
        "/admin/providers/PROVIDER-SYNTHETIC/credentials",
        "/admin/providers/PROVIDER-SYNTHETIC/feeds",
    ]

    def respond(request):
        if request.url.path == expected[0]:
            return httpx.Response(200, json={"id": "ORG-SYNTHETIC"})
        if request.url.path == expected[1]:
            return httpx.Response(200, json={"id": "PROVIDER-SYNTHETIC"})
        if request.url.path == expected[2]:
            return httpx.Response(200, json={
                "credential_id": "PCRED-SYNTHETIC",
                "api_key": api_secret,
                "label": "initial-onboarding",
            })
        if request.url.path == expected[3]:
            return httpx.Response(500, text=f"internal error: {error_secret}")
        raise AssertionError("Unexpected synthetic request")

    code, captured, calls, target = _run_provisioning_mocked(
        monkeypatch, capsys, tmp_path, respond
    )
    assert code == 1
    assert calls == expected
    assert target.exists()
    assert json.loads(target.read_text())["provider_api_key"] == api_secret
    assert api_secret not in captured.out + captured.err
    assert error_secret not in captured.out + captured.err
    assert "inspect tenant state" in captured.err.lower()


def test_provider_credential_file_must_be_outside_public_checkout(
    monkeypatch, tmp_path, capsys
):
    """Reject accidental Git-tracked secrets before making an admin API call."""
    import sys

    target = ROOT / "scripts" / f"synthetic-{tmp_path.name}-secret.json"
    assert not target.exists()
    with pytest.raises(ValueError, match="outside the SignalGate repository"):
        provision.validate_credential_output(str(target))

    clients = []
    monkeypatch.setattr(
        provision.httpx, "Client",
        lambda *args, **kwargs: clients.append((args, kwargs)),
    )
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT), "--backend", "https://example.invalid",
        "--admin-id", "TEST-ONLY", "--organization-name", "Fictional Org",
        "--provider-name", "Fictional Provider",
        "--credential-output", str(target),
    ])
    with pytest.raises(SystemExit) as failure:
        provision.main()
    assert failure.value.code == 2
    assert clients == [], "No client may be constructed for checkout secrets"
    assert not target.exists()
    assert "outside the SignalGate repository" in capsys.readouterr().err


def test_provider_credential_symlink_parent_cannot_route_secret_into_repo(tmp_path):
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(ROOT / "scripts", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unsupported here")
    target = alias / f"synthetic-{tmp_path.name}-credential.json"
    assert not target.exists()
    with pytest.raises(ValueError, match="outside the SignalGate repository"):
        provision.validate_credential_output(str(target))


def test_external_private_credential_output_remains_accepted(tmp_path):
    target = tmp_path / "fresh-credential.json"
    assert provision.validate_credential_output(str(target)) == target
    assert not target.exists()


def test_provisioning_admin_client_ignores_ambient_proxy_ca_and_redirects(
    monkeypatch, tmp_path,
):
    """No network or provider state mutation; construction is intercepted."""
    import sys

    class NoNetwork(RuntimeError):
        pass

    observed = []

    def blocking_client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["base_url"] == "https://provider.example.invalid"
        assert kwargs["headers"]["X-Admin-Id"] == "SYNTHETIC-ADMIN"
        assert kwargs["headers"]["X-Admin-API-Key"] == "SYNTHETIC-ADMIN-KEY"
        observed.append(True)
        raise NoNetwork("synthetic: no admin API")

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/untrusted/ca.pem")
    monkeypatch.delenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", raising=False)
    monkeypatch.setattr(provision.httpx, "Client", blocking_client)
    target = tmp_path / "not-created-secret.json"
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT),
        "--backend", "https://provider.example.invalid",
        "--admin-id", "SYNTHETIC-ADMIN",
        "--admin-api-key", "SYNTHETIC-ADMIN-KEY",
        "--organization-name", "Fictional Organisation",
        "--provider-name", "Fictional Provider",
        "--credential-output", str(target),
    ])

    with pytest.raises(NoNetwork, match="synthetic: no admin API"):
        provision.main()
    assert observed == [True]
    assert not target.exists()
