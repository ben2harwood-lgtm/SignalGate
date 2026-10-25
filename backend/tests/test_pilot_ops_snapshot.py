"""Read-only monitoring observation must never mutate or expose admin identity."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat

import httpx
import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "pilot_ops_snapshot.py"
spec = importlib.util.spec_from_file_location("pilot_ops_snapshot", SOURCE)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def fake_poll(
    monkeypatch, *, metrics_status=200, counters=None, malformed=False,
    ready_status=200, ready_payload=None, health_status=200, health_payload=None,
):
    original = httpx.Client
    seen = []
    base_counts = {
        "mode": {"demo_only": True, "admin_paused": True},
        "pipeline": {
            "commands_pending": 0, "commands_sent_to_ea": 0,
            "commands_sent_to_ea_stale_60s": 0, "commands_failed": 0,
            "executions_failed": 0, "management_failures": 0,
        },
        "assurance": {
            "reconciliation_conflicts": 0, "execution_report_conflicts": 0,
            "signal_replay_conflicts": 0, "execution_reports_recovered": 0,
        },
        "tenancy": {
            "providers_total": 1, "providers_paused": 1,
            "feeds_total": 1, "feeds_paused": 1,
        },
    }
    if counters is not None:
        base_counts.update(counters)

    def respond(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/readyz":
            assert "x-admin-api-key" not in request.headers
            assert "x-admin-id" not in request.headers
            return httpx.Response(
                ready_status,
                json={"status": "ready"} if ready_payload is None else ready_payload,
            )
        if request.url.path == "/health":
            assert "x-admin-api-key" not in request.headers
            assert "x-admin-id" not in request.headers
            return httpx.Response(
                health_status,
                json=(
                    {"status": "ok", "demo_only_mode": True, "admin_paused": True}
                    if health_payload is None else health_payload
                ),
            )
        if request.url.path == "/admin/metrics":
            assert request.headers.get("x-admin-id") == "operator-test-id"
            assert request.headers.get("x-admin-api-key") == "secret-test-key"
            if malformed:
                return httpx.Response(metrics_status, content="not-json")
            return httpx.Response(metrics_status, json=base_counts)
        return httpx.Response(404)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        snapshot.httpx, "Client",
        lambda *args, **kwargs: original(*args, transport=transport, **kwargs),
    )
    return seen


def take():
    return snapshot.collect(
        backend="https://pilot.example.invalid",
        admin_id="operator-test-id",
        admin_api_key="secret-test-key",
        candidate_sha="c" * 40,
    )


def test_observation_reads_only_exact_routes_and_never_records_admin_secret(
    monkeypatch, tmp_path,
):
    seen = fake_poll(monkeypatch)
    receipt = take()
    assert receipt["result"] == "COLLECTED"
    assert seen == [
        ("GET", "/readyz"),
        ("GET", "/health"),
        ("GET", "/admin/metrics"),
    ]
    assert receipt["candidate_sha_verified_by_backend"] is False
    assert receipt["authenticated_metrics_attempted"] is True
    assert receipt["review_historical_totals"] == []
    assert "secret-test-key" not in json.dumps(receipt)
    assert "operator-test-id" not in json.dumps(receipt)
    path = snapshot.write_receipt(receipt, tmp_path / "receipts")
    assert path.exists() and path.parent.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text()) == receipt


def test_historical_conflicts_are_flagged_for_review_not_claimed_as_new_incident(
    monkeypatch,
):
    fake_poll(monkeypatch, counters={
        "assurance": {
            "reconciliation_conflicts": 2, "execution_report_conflicts": 0,
            "signal_replay_conflicts": 0, "execution_reports_recovered": 0,
        }
    })
    receipt = take()
    assert receipt["result"] == "REVIEW_REQUIRED"
    assert receipt["review_historical_totals"] == [{
        "group": "assurance", "counter": "reconciliation_conflicts", "total": 2,
    }]
    assert receipt["scope"] == "single_readonly_observation_not_slo_or_alerting"


@pytest.mark.parametrize("failure_mode", ["wrong_credentials", "invalid_json", "bad_counter"])
def test_missing_or_malformed_metrics_fail_closed(monkeypatch, failure_mode):
    fake_poll(
        monkeypatch,
        metrics_status=403 if failure_mode == "wrong_credentials" else 200,
        malformed=failure_mode == "invalid_json",
        counters={"pipeline": {"commands_pending": "fake"}} if failure_mode == "bad_counter" else None,
    )
    receipt = take()
    assert receipt["result"] == "FAIL"
    assert (
        not receipt["checks"]["admin_auth"] if failure_mode != "bad_counter"
        else not receipt["checks"]["pipeline_counters"]
    )


def test_admin_credentials_and_candidate_identity_required_before_any_network():
    with pytest.raises(ValueError):
        snapshot.collect(
            backend="https://pilot.example.invalid",
            admin_id="operator-test-id",
            admin_api_key="",
            candidate_sha="c" * 40,
        )
    with pytest.raises(ValueError):
        snapshot.collect(
            backend="https://pilot.example.invalid",
            admin_id="operator-test-id",
            admin_api_key="secret-test-key",
            candidate_sha="not-a-sha",
        )


@pytest.mark.parametrize(
    ("probe", "status", "payload"),
    [
        ("readyz", 503, {"status": "not_ready"}),
        ("readyz", 200, {"status": "starting"}),
        ("readyz", 200, []),
        ("health", 503, {"status": "unavailable", "demo_only_mode": True}),
        ("health", 200, {"status": "starting", "demo_only_mode": True}),
        ("health", 200, {"status": "ok", "demo_only_mode": False}),
        ("health", 200, {"status": "ok", "demo_only_mode": "true"}),
        ("health", 200, []),
    ],
)
def test_bad_public_preflight_never_sends_admin_headers(
    monkeypatch, probe, status, payload,
):
    options = (
        {"ready_status": status, "ready_payload": payload}
        if probe == "readyz"
        else {"health_status": status, "health_payload": payload}
    )
    seen = fake_poll(monkeypatch, **options)
    receipt = take()
    assert seen == [("GET", "/readyz"), ("GET", "/health")]
    assert receipt["result"] == "FAIL"
    assert receipt["authenticated_metrics_attempted"] is False
    assert receipt["http_status_codes"]["admin_metrics"] is None
    assert receipt["checks"]["admin_auth"] is False
    assert receipt["checks"]["metrics_demo_only"] is False
    assert receipt["checks"]["pipeline_counters"] is False
    assert "secret-test-key" not in json.dumps(receipt)
    assert "operator-test-id" not in json.dumps(receipt)


def test_snapshot_against_real_fastapi_metrics_and_readiness(client, monkeypatch):
    """Run the operator tool against actual app routes, not only fake JSON."""
    original = httpx.Client
    seen = []
    secret = "synthetic-admin-secret"

    def handle(request):
        seen.append((request.method, request.url.path))
        assert request.method == "GET"
        response = client.request(
            "GET",
            request.url.path,
            headers={
                "X-Admin-Id": request.headers.get("x-admin-id", ""),
                "X-Admin-API-Key": request.headers.get("x-admin-api-key", ""),
            },
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        snapshot.httpx, "Client",
        lambda *args, **kwargs: original(*args, transport=transport, **kwargs),
    )
    receipt = snapshot.collect(
        backend="https://pilot.example.invalid",
        admin_id="999",  # test-fixture admin, not a real user
        admin_api_key=secret,
        candidate_sha="c" * 40,
    )
    assert receipt["result"] == "COLLECTED", receipt["checks"]
    assert seen == [
        ("GET", "/readyz"), ("GET", "/health"), ("GET", "/admin/metrics"),
    ]
    assert receipt["counts"]["pipeline"]["commands_sent_to_ea_stale_60s"] == 0
    assert secret not in json.dumps(receipt)
    assert '"admin_id"' not in json.dumps(receipt)
