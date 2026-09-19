"""Observability and telemetry safety tests."""
from __future__ import annotations

import logging

from .conftest import ADMIN_HEADERS


def test_request_id_and_security_headers_are_emitted(client, caplog):
    caplog.set_level(logging.INFO, logger="signalgate.request")
    response = client.get(
        "/health?token=do-not-log-this",
        headers={"X-Request-Id": "req-test-123"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-test-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"

    messages = [record.getMessage() for record in caplog.records]
    request_log = next(message for message in messages if '"event":"http_request"' in message)
    assert '"request_id":"req-test-123"' in request_log
    assert '"path":"/health"' in request_log
    assert "do-not-log-this" not in request_log
    assert "token=" not in request_log


def test_operational_metrics_are_admin_gated_and_secret_free(client):
    denied = client.get("/admin/metrics")
    assert denied.status_code == 403

    allowed = client.get("/admin/metrics", headers=ADMIN_HEADERS)
    assert allowed.status_code == 200
    body = allowed.json()
    assert set(body) == {"mode", "tenancy", "pipeline", "assurance"}

    flattened = str(body).lower()
    for forbidden in (
        "license_key",
        "api_key",
        "telegram_user_id",
        "raw_text",
        "password",
        "secret",
    ):
        assert forbidden not in flattened


def test_metrics_include_stale_command_and_conflict_counters(client):
    body = client.get("/admin/metrics", headers=ADMIN_HEADERS).json()
    assert "commands_sent_to_ea_stale_60s" in body["pipeline"]
    assert "reconciliation_conflicts" in body["assurance"]
    assert "execution_report_conflicts" in body["assurance"]
    assert "signal_replay_conflicts" in body["assurance"]
