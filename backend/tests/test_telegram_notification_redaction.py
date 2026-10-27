"""Offline privacy regressions for best-effort Telegram delivery logging."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import httpx

from app import telegram_service


def test_disabled_notification_does_not_log_message_or_chat(monkeypatch, caplog):
    monkeypatch.setattr(telegram_service.settings, "telegram_bot_token", "replace_me")

    def unexpected_post(*args, **kwargs):
        raise AssertionError("disabled path must not issue network request")

    monkeypatch.setattr(telegram_service.httpx, "post", unexpected_post)
    with caplog.at_level(logging.DEBUG, logger="signalgate.telegram"):
        assert not telegram_service.send_message("PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER")
    assert "disabled" in caplog.text
    assert "PRIVATE_CHAT_MARKER" not in caplog.text
    assert "PRIVATE_SIGNAL_MARKER" not in caplog.text


def test_transport_failure_logs_no_token_message_or_chat(monkeypatch, caplog):
    token = "12345:BOT_CREDENTIAL_MARKER"
    monkeypatch.setattr(telegram_service.settings, "telegram_bot_token", token)

    def failing_post(url, **kwargs):
        assert token in url
        assert kwargs["json"]["chat_id"] == "PRIVATE_CHAT_MARKER"
        raise httpx.ConnectError("HTTP connection failed: BOT_CREDENTIAL_MARKER PRIVATE_SIGNAL_MARKER")

    monkeypatch.setattr(telegram_service.httpx, "post", failing_post)
    with caplog.at_level(logging.WARNING, logger="signalgate.telegram"):
        assert not telegram_service.send_message("PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER")
    assert "notification failed" in caplog.text
    for marker in ("BOT_CREDENTIAL_MARKER", "PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER"):
        assert marker not in caplog.text


def test_http_rejection_is_nonfatal_and_does_not_log_response(monkeypatch, caplog):
    monkeypatch.setattr(telegram_service.settings, "telegram_bot_token", "12345:BOT_CREDENTIAL_MARKER")
    monkeypatch.setattr(
        telegram_service.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=403, text="PRIVATE_RESPONSE_MARKER"),
    )
    with caplog.at_level(logging.DEBUG, logger="signalgate.telegram"):
        assert not telegram_service.send_message("PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER")
    assert "BOT_CREDENTIAL_MARKER" not in caplog.text
    assert "PRIVATE_RESPONSE_MARKER" not in caplog.text
    assert "PRIVATE_CHAT_MARKER" not in caplog.text
    assert "PRIVATE_SIGNAL_MARKER" not in caplog.text


def test_successful_send_preserves_functionality_without_logging_payload(monkeypatch, caplog):
    token = "12345:LOCAL_SYNTHETIC_TOKEN"
    monkeypatch.setattr(telegram_service.settings, "telegram_bot_token", token)
    captured = {}

    def successful_post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(telegram_service.httpx, "post", successful_post)
    with caplog.at_level(logging.DEBUG, logger="signalgate.telegram"):
        assert telegram_service.send_message("PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER")
    assert captured["url"] == "https://api.telegram.org/bot" + token + "/sendMessage"
    assert captured["kwargs"]["json"] == {
        "chat_id": "PRIVATE_CHAT_MARKER",
        "text": "PRIVATE_SIGNAL_MARKER",
    }
    assert captured["kwargs"]["timeout"] == 5.0
    for marker in (token, "PRIVATE_CHAT_MARKER", "PRIVATE_SIGNAL_MARKER"):
        assert marker not in caplog.text


def test_httpx_info_request_log_cannot_expose_telegram_api_token(caplog):
    # Exercise actual HTTPX logging with an offline transport and no network.
    marker = "SYNTHETIC_BOT_PATH_TOKEN_MARKER"
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    with caplog.at_level(logging.INFO):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            response = client.post("https://api.telegram.org/bot" + marker + "/sendMessage")
    assert response.status_code == 200
    assert marker not in caplog.text
