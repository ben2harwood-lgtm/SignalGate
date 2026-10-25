"""No provider credentials after an unhealthy/non-demo public preflight.

Every response below uses synthetic HTTPX MockTransport; no socket or broker.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "sg_preflight_public_gate", ROOT / "scripts" / "pilot_preflight.py"
)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.mark.parametrize(
    ("broken_path", "status_code", "payload"),
    [
        ("/health", 503, {"status": "ok", "demo_only_mode": True}),
        ("/health", 200, "{invalid-json"),
        ("/health", 200, []),
        ("/health", 200, {"demo_only_mode": True}),
        ("/health", 200, {"status": "unhealthy", "demo_only_mode": True}),
        ("/health", 200, {"status": "ok", "demo_only_mode": False}),
        ("/health", 200, {"status": "ok", "demo_only_mode": "true"}),
        ("/health", 200, {
            "status": "ok", "demo_only_mode": True, "admin_paused": "false"
        }),
        ("/readyz", 503, {"status": "ready"}),
        ("/readyz", 200, "{invalid-json"),
        ("/readyz", 200, ["ready"]),
        ("/readyz", 200, {"status": "not_ready"}),
    ],
)
def test_public_gate_fails_without_sending_credentials(
    monkeypatch, broken_path, status_code, payload
):
    secret = "SYNTHETIC_PROVIDER_KEY_NEVER_SEND"
    paths = []
    client_constructor = httpx.Client

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.method == "GET"
        assert request.url.path in {"/health", "/readyz"}, (
            "provider-authenticated route called before demo-readiness gate"
        )
        assert "x-provider-api-key" not in request.headers
        assert "x-provider-id" not in request.headers
        if request.url.path == broken_path:
            if isinstance(payload, (dict, list)):
                return httpx.Response(status_code, json=payload)
            return httpx.Response(status_code, content=payload)
        if request.url.path == "/health":
            return httpx.Response(200, json={
                "status": "ok", "demo_only_mode": True, "admin_paused": False
            })
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        preflight.httpx,
        "Client",
        lambda *args, **kwargs: client_constructor(
            *args, transport=transport, **kwargs
        ),
    )
    receipt = preflight.run_preflight(
        backend="https://pilot.example.invalid",
        provider_id="PRV-SYNTHETIC",
        provider_api_key=secret,
        declared_candidate_sha="a" * 40,
        require_feeds_paused=True,
    )
    assert paths == ["/health", "/readyz"]
    assert receipt["result"] == "FAIL"
    assert receipt["candidate_sha_verified_by_backend"] is False
    assert receipt["evidence"].get("provider_export_sha256") is None
    assert receipt["evidence"].get("provider_status") is None
    assert any(
        check["name"] == "credentialled_provider_checks"
        and check["passed"] is False
        and check["detail"].startswith("NOT_RUN")
        for check in receipt["checks"]
    )
    assert secret not in json.dumps(receipt)
