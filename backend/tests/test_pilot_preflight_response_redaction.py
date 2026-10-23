"""Synthetic untrusted backend payloads cannot become preflight receipt text.

These tests do not open sockets or send real provider credentials.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_preflight.py"
SPEC = importlib.util.spec_from_file_location("preflight_response_redaction", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_untrusted_response_metadata_is_redacted_and_fails_closed(monkeypatch, tmp_path):
    poison = "SYNTHETIC_PRIVATE_BACKEND_VALUE_DO_NOT_SAVE"
    key = "SYNTHETIC_TEST_ONLY_PROVIDER_KEY"
    seen = []
    original_client = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        seen.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={
                "demo_only_mode": True, "admin_paused": poison,
            })
        if request.url.path == "/readyz":
            return httpx.Response(200, json={"status": poison})
        if request.url.path == "/providers/me":
            if request.headers.get("x-provider-api-key") != key:
                return httpx.Response(401)
            return httpx.Response(200, json={
                "id": poison, "status": poison, "paused": poison,
            })
        if request.url.path == "/providers/me/feeds":
            return httpx.Response(200, json=[{
                "id": "UNEXPECTED-" + poison, "paused": poison,
            }])
        if request.url.path == "/providers/me/overview":
            return httpx.Response(200, json={
                "provider": {"id": "PRV-TEST"},
                "feed_count": poison, "active_accounts": True,
                "command_count": -4,
            })
        if request.url.path == "/providers/me/export":
            return httpx.Response(200, json={
                "provider": {"id": "PRV-TEST"},
                poison: {"token_hash": "FAKE_SECRET"},
                "summary": {"feed_count": poison},
            })
        raise AssertionError("Unexpected read-only route: " + request.url.path)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        preflight.httpx, "Client",
        lambda *args, **kwargs: original_client(
            *args, transport=transport, **kwargs
        ),
    )
    receipt = preflight.run_preflight(
        backend="https://demo.example.invalid",
        provider_id="PRV-TEST",
        provider_api_key=key,
        declared_candidate_sha="c" * 40,
        require_feeds_paused=True,
    )
    assert seen == [
        "/health", "/readyz", "/providers/me", "/providers/me",
        "/providers/me/feeds", "/providers/me/overview", "/providers/me/export",
    ]
    assert receipt["result"] == "FAIL"
    assert receipt["evidence"]["admin_paused"] is None
    assert receipt["evidence"]["provider_status"] == "INACTIVE_OR_UNKNOWN"
    assert receipt["evidence"]["provider_paused"] is None
    assert receipt["evidence"]["feed_ids"] == []
    assert "feed_count" not in receipt["evidence"]
    assert "active_accounts" not in receipt["evidence"]
    assert "command_count" not in receipt["evidence"]
    assert receipt["evidence"]["provider_export_summary"] == {}
    rejected = {check["name"] for check in receipt["checks"] if not check["passed"]}
    assert {
        "health_metadata_types", "readiness", "provider_auth", "provider_active",
        "provider_metadata_types", "feed_metadata_types", "overview_count_types",
        "provider_export_secret_fields_absent",
    } <= rejected
    encoded = json.dumps(receipt)
    assert poison not in encoded
    assert key not in encoded
    assert "FAKE_SECRET" not in encoded

    directory = preflight.write_receipt(receipt, tmp_path / "receipts")
    # The tool writes both machine and human receipts; neither may echo API text.
    for filename in ("receipt.json", "receipt.md"):
        written = (directory / filename).read_text(encoding="utf-8")
        assert poison not in written
        assert key not in written
        assert "FAKE_SECRET" not in written


def test_valid_typed_operational_fields_remain_useful(monkeypatch):
    key = "TEST_ONLY_KEY"
    original_client = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={
                "demo_only_mode": True, "admin_paused": False,
            })
        if request.url.path == "/readyz":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/providers/me":
            if request.headers.get("x-provider-api-key") != key:
                return httpx.Response(401)
            return httpx.Response(200, json={
                "id": "PRV-TEST", "status": "ACTIVE", "paused": True,
            })
        if request.url.path == "/providers/me/feeds":
            return httpx.Response(200, json=[{
                "id": "FED-AB12", "paused": True,
            }])
        if request.url.path == "/providers/me/overview":
            return httpx.Response(200, json={
                "provider": {"id": "PRV-TEST"},
                "feed_count": 1, "active_accounts": 0,
            })
        if request.url.path == "/providers/me/export":
            return httpx.Response(200, json={
                "provider": {"id": "PRV-TEST"},
                "summary": {"feed_count": 1},
            })
        raise AssertionError("Unexpected request")

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        preflight.httpx, "Client",
        lambda *args, **kwargs: original_client(
            *args, transport=transport, **kwargs
        ),
    )
    receipt = preflight.run_preflight(
        backend="https://demo.example.invalid",
        provider_id="PRV-TEST",
        provider_api_key=key,
        declared_candidate_sha="d" * 40,
        require_feeds_paused=True,
    )
    assert receipt["result"] == "PASS", receipt["checks"]
    assert receipt["evidence"]["feed_ids"] == ["FED-AB12"]
    assert receipt["evidence"]["provider_status"] == "ACTIVE"
    assert receipt["evidence"]["admin_paused"] is False
    assert receipt["evidence"]["feed_count"] == 1
    assert key not in json.dumps(receipt)
