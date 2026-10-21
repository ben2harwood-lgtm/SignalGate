"""Provider pilot preflight helper tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_preflight.py"
SPEC = importlib.util.spec_from_file_location("pilot_preflight", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("https://api.example.test/", "https://api.example.test"),
    ],
)
def test_backend_url_validation(raw, expected):
    assert preflight.validate_backend_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://api.example.test",
        "https://user:pass@example.test",
        "https://api.example.test/path?secret=x",
        "https://api.example.test/api",
        "ftp://api.example.test",
        "not-a-url",
    ],
)
def test_backend_url_rejects_unsafe_values(raw):
    with pytest.raises(ValueError):
        preflight.validate_backend_url(raw)


def test_mutated_secret_is_never_same():
    assert preflight.mutate_secret("sgp_example") != "sgp_example"
    assert preflight.mutate_secret("x") != "x"


def test_export_secret_field_scanner_is_recursive():
    payload = {
        "provider": {"id": "PROVIDER-1"},
        "feeds": [{"id": "FEED-1", "subscribers": [{"license_key": "never"}]}],
        "history": [{"nested": {"token_hash": "never"}}],
    }
    hits = preflight.find_forbidden_keys(payload)
    assert "$.feeds[0].subscribers[0].license_key" in hits
    assert "$.history[0].nested.token_hash" in hits


def test_export_scanner_allows_expected_operating_metadata():
    payload = {
        "provider": {"id": "PROVIDER-1", "name": "Example", "paused": True},
        "feeds": [{"id": "FEED-1", "paused": True}],
        "signals": [{"id": "SIG-1", "symbol": "XAUUSD", "direction": "BUY"}],
        "summary": {"signal_count_in_export": 1},
    }
    assert preflight.find_forbidden_keys(payload) == []


def test_candidate_sha_must_be_canonical_before_network_calls():
    with pytest.raises(ValueError):
        preflight.run_preflight(
            backend="http://127.0.0.1:8000",
            provider_id="PROVIDER-1",
            provider_api_key="sgp_example",
            declared_candidate_sha="not-a-sha",
            require_feeds_paused=True,
        )


def test_read_only_preflight_checks_real_provider_flow_without_leaking_key(monkeypatch):
    import json
    import httpx

    original_client = httpx.Client
    provider_key = "secret-preflight-test-key"
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"demo_only_mode": True, "admin_paused": True})
        if request.url.path == "/readyz":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/providers/me":
            supplied_key = request.headers.get("x-provider-api-key")
            if supplied_key != provider_key:
                return httpx.Response(401, json={"detail": "Unauthorized"})
            return httpx.Response(200, json={"id": "PRV-1", "paused": False, "status": "ACTIVE"})
        if request.url.path == "/providers/me/feeds":
            return httpx.Response(200, json=[{"id": "FED-1", "paused": True}])
        if request.url.path == "/providers/me/overview":
            return httpx.Response(200, json={"provider": {"id": "PRV-1"}, "feed_count": 1})
        if request.url.path == "/providers/me/export":
            return httpx.Response(200, json={
                "provider": {"id": "PRV-1"},
                "summary": {"signal_count_in_export": 1},
            })
        return httpx.Response(404, json={"detail": "Unknown route"})

    transport = httpx.MockTransport(handle)

    def mock_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(preflight.httpx, "Client", mock_client)
    receipt = preflight.run_preflight(
        backend="https://api.example.test",
        provider_id="PRV-1",
        provider_api_key=provider_key,
        declared_candidate_sha="a" * 40,
        require_feeds_paused=True,
    )
    assert receipt["result"] == "PASS", receipt["checks"]
    assert receipt["candidate_sha_verified_by_backend"] is False
    assert all(method == "GET" for method, _ in seen)
    assert len(seen) == 7
    assert provider_key not in json.dumps(receipt)
    assert receipt["evidence"]["feed_ids"] == ["FED-1"]


@pytest.mark.parametrize(("unpaused", "leaks_secret"), [
    (True, False),
    (False, True),
])
def test_preflight_fails_closed_on_unpaused_feed_or_export_secret(monkeypatch, unpaused, leaks_secret):
    import httpx

    original_client = httpx.Client

    def handle(request):
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"demo_only_mode": True})
        if path == "/readyz":
            return httpx.Response(200, json={"status": "ready"})
        if path == "/providers/me":
            if request.headers.get("x-provider-api-key") != "provider-key":
                return httpx.Response(401)
            return httpx.Response(200, json={"id": "PRV-1"})
        if path == "/providers/me/feeds":
            return httpx.Response(200, json=[{"id": "FED-1", "paused": not unpaused}])
        if path == "/providers/me/overview":
            return httpx.Response(200, json={"provider": {"id": "PRV-1"}})
        if path == "/providers/me/export":
            record = {"provider": {"id": "PRV-1"}}
            if leaks_secret:
                record["history"] = [{"token_hash": "should-never-export"}]
            return httpx.Response(200, json=record)
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        preflight.httpx, "Client",
        lambda *args, **kwargs: original_client(*args, transport=transport, **kwargs),
    )
    receipt = preflight.run_preflight(
        backend="https://api.example.test",
        provider_id="PRV-1",
        provider_api_key="provider-key",
        declared_candidate_sha="b" * 40,
        require_feeds_paused=True,
    )
    assert receipt["result"] == "FAIL"
    failed = {item["name"] for item in receipt["checks"] if not item["passed"]}
    assert ("feeds_paused_before_cohort" if unpaused else
            "provider_export_secret_fields_absent") in failed


def test_read_only_preflight_against_real_fastapi_routes(client, db, monkeypatch):
    """Validate the operator tool against actual app routes, not stubbed JSON."""
    import json
    import httpx
    from app import models
    from .test_provider_export import _provider

    provider, feed, secret = _provider(db, "preflight-real-routes")
    # Low-level fixture creation bypasses the HTTP onboarding route, so put the
    # test feed into the same explicitly paused pre-cohort state as production.
    feed.paused = True
    db.commit()
    assert feed.paused is True
    original_http_client = httpx.Client
    calls = []
    initial_commands = db.query(models.Command).count()

    def backend_transport(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "preflight must never mutate app state"
        response = client.request(
            request.method,
            request.url.path,
            headers=dict(request.headers),
        )
        return httpx.Response(
            status_code=response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )

    transport = httpx.MockTransport(backend_transport)
    monkeypatch.setattr(
        preflight.httpx,
        "Client",
        lambda *args, **kwargs: original_http_client(
            *args, transport=transport, **kwargs
        ),
    )
    receipt = preflight.run_preflight(
        backend="https://pilot.example.test",
        provider_id=provider.id,
        provider_api_key=secret,
        declared_candidate_sha="f" * 40,
        require_feeds_paused=True,
    )

    assert receipt["result"] == "PASS", receipt["checks"]
    assert receipt["candidate_sha_verified_by_backend"] is False
    assert len(calls) == 7
    assert all(method == "GET" for method, _ in calls)
    assert receipt["evidence"]["feed_ids"] == [feed.id]
    assert secret not in json.dumps(receipt)
    assert db.query(models.Command).count() == initial_commands
