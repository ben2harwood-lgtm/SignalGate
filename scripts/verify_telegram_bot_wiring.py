#!/usr/bin/env python3
"""Offline smoke for hosted Telegram handler wiring; NEVER calls Telegram API.

Run in an isolated environment with telegram_bot/requirements.txt installed.
The bot and its handlers must be importable and register hosted commands without
any backend, broker, user account, internet access or real credentials.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import httpx

# Force synthetic credentials before importing config or instantiating the bot.
# This test must never pick up a developer's real token or hosted .env.
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:OFFLINE_TEST_ONLY"
os.environ["REQUIRE_LICENSE"] = "true"
os.environ["BACKEND_BASE_URL"] = "https://unreachable.example.invalid"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler  # noqa: E402
from bot import build_application  # noqa: E402
from config import config  # noqa: E402
import handlers  # noqa: E402


def check_backend_http_fail_closed() -> None:
    """HTTP errors must never look like accepted decisions; no outbound traffic."""
    original_client = httpx.AsyncClient
    calls = []

    async def exercise(method: str, status: int, valid_json: bool):
        def respond(request):
            calls.append((request.method, request.url.path))
            if not valid_json:
                return httpx.Response(status, content="not-json")
            return httpx.Response(status, json={"result": "APPROVED"})

        transport = httpx.MockTransport(respond)
        with patch.object(
            handlers.httpx, "AsyncClient",
            lambda *args, **kwargs: original_client(*args, transport=transport, **kwargs),
        ):
            if method == "GET":
                return await handlers._backend_get("/fake", params={"key": "SECRET-NEVER-LOG"})
            return await handlers._backend_post("/fake", json={"token": "SECRET-NEVER-LOG"})

    assert asyncio.run(exercise("POST", 403, True)) is None
    assert asyncio.run(exercise("POST", 500, True)) is None
    assert asyncio.run(exercise("POST", 200, False)) is None
    assert asyncio.run(exercise("GET", 404, True)) is None
    assert asyncio.run(exercise("POST", 200, True)) == {"result": "APPROVED"}
    assert calls == [("POST", "/fake"), ("POST", "/fake"),
                     ("POST", "/fake"), ("GET", "/fake"), ("POST", "/fake")]


def check_unconfirmed_decision_does_not_claim_approval() -> None:
    """Even a malformed nominally successful body must not produce APPROVED UI."""
    seen = []
    called = []
    async def fake_post(path, **kwargs):
        called.append(path)
        return {"detail": "backend error without result"}

    class Query:
        data = "YES:SIG-TEST"
        from_user = SimpleNamespace(id=1)
        message = SimpleNamespace(text="Synthetic demo trade card")

        async def answer(self):
            pass

        async def edit_message_text(self, message):
            seen.append(message)

    with patch.object(handlers, "_backend_post", fake_post):
        asyncio.run(handlers.on_decision(SimpleNamespace(callback_query=Query()), None))
    assert len(seen) == 1 and "could not be confirmed" in seen[0].lower()
    assert "Approved. Waiting" not in seen[0]
    assert called == ["/signals/SIG-TEST/approve"]

    called.clear()
    seen.clear()
    class InvalidQuery(Query):
        data = "UNKNOWN:SIG-TEST"

    with patch.object(handlers, "_backend_post", fake_post):
        asyncio.run(handlers.on_decision(SimpleNamespace(callback_query=InvalidQuery()), None))
    assert seen == ["Invalid action."]
    assert not called



def check_screenshot_extraction_fail_closed() -> None:
    """No stale previews, credential-bearing errors, or hosted legacy fallback."""
    original_client = httpx.AsyncClient
    secret = "SYNTHETIC-SECRET-NOT-FOR-TELEGRAM"

    async def connected(_user_id):
        return {"feed_id": "FEED-OFFLINE"}

    async def disconnected(_user_id):
        return None

    def exercise(*, status=500, body="", payload=None, fail=None, source=connected):
        replies = []
        warnings = []
        requests = []
        user_state = {"pending_signal_text": "OLD-NOT-APPROVED", "awaiting_edit": True}

        async def reply_text(message, **_kwargs):
            replies.append(message)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123456),
            message=SimpleNamespace(reply_text=reply_text),
        )
        context = SimpleNamespace(user_data=user_state)

        def respond(request):
            requests.append(request.url.path)
            if fail is not None:
                raise RuntimeError(fail)
            if payload is not None:
                return httpx.Response(status, json=payload)
            return httpx.Response(status, text=body)

        transport = httpx.MockTransport(respond)
        with (
            patch.object(handlers, "_provider_source_status", source),
            patch.object(
                handlers.httpx,
                "AsyncClient",
                lambda *args, **kwargs: original_client(
                    *args, transport=transport, **kwargs
                ),
            ),
            patch.object(
                handlers.logger,
                "warning",
                lambda fmt, *args: warnings.append(fmt % args),
            ),
        ):
            asyncio.run(
                handlers._preview_screenshot(
                    update=update,
                    context=context,
                    image_bytes=b"SYNTHETIC-IMAGE-NO-USER-DATA",
                    mime="image/jpeg",
                )
            )
        return replies, warnings, requests, user_state

    for status in (403, 500):
        replies, warnings, requests, state = exercise(
            status=status, body=f"upstream stack and token={secret}"
        )
        assert len(replies) == 1 and "rejected" in replies[0].lower()
        assert requests == ["/provider-sources/telegram/extract"]
        assert all(secret not in item for item in replies + warnings)
        assert any(str(status) in warning for warning in warnings)
        assert state == {}, "Failed extraction retained an earlier unsent preview"

    replies, warnings, requests, state = exercise(fail=f"backend URL token={secret}")
    assert len(replies) == 1 and "couldn't read" in replies[0].lower()
    assert requests == ["/provider-sources/telegram/extract"]
    assert all(secret not in item for item in replies + warnings)
    assert any("RuntimeError" in warning for warning in warnings)
    assert state == {}

    replies, warnings, requests, state = exercise(source=disconnected)
    assert len(replies) == 1 and "no longer connected" in replies[0].lower()
    assert not requests, "Hosted source revocation fell through to legacy extraction"
    assert not warnings
    assert state == {}

    # A nominal HTTP 200 is not sufficient: JSON type and all fields are untrusted.
    malformed = [
        ("array root", [], ""),
        ("null root", None, "null"),
        ("non-string text", {"parser_status": "VALID", "extracted_text": []}, ""),
        ("non-string status", {"parser_status": ["VALID"], "extracted_text": "BUY"}, ""),
        ("empty valid signal", {"parser_status": "VALID", "extracted_text": "  "}, ""),
        ("long text", {"parser_status": "VALID", "extracted_text": "B" * 5000}, ""),
        ("long notes", {"parser_status": "VALID", "extracted_text": "BUY", "notes": "N" * 5000}, ""),
        ("bad number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": []}, ""),
        ("bool number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": True}, ""),
        ("huge number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": 10 ** 400}, ""),
        ("non-finite number", {"parser_status": "VALID", "extracted_text": "BUY", "tp1": float("nan")}, ""),
        ("invalid unicode", {"parser_status": "VALID", "extracted_text": "\ud800"}, ""),
        ("combined preview", {
            "parser_status": "VALID", "extracted_text": "B" * 1900, "notes": "N" * 1900
        }, ""),
        ("UTF16 preview", {
            "parser_status": "VALID", "extracted_text": "🚀" * 1400, "notes": "🚀" * 600
        }, ""),
    ]
    for label, payload, body in malformed:
        replies, warnings, requests, state = exercise(
            status=200, payload=payload, body=body
        )
        assert requests == ["/provider-sources/telegram/extract"], label
        assert len(replies) == 1 and "nothing was saved" in replies[0].lower(), label
        assert state == {}, f"{label} retained stale or confirmable text"
        assert not any("B" * 64 in item or "N" * 64 in item for item in replies + warnings)

    replies, warnings, requests, state = exercise(
        status=200,
        payload={
            "parser_status": "VALID",
            "extracted_text": "EURUSD BUY SL 1.05 TP1 1.07",
            "symbol": "EURUSD",
            "direction": "BUY",
            "initial_stop_loss": 1.05,
            "tp1": 1.07,
            "confidence": "HIGH",
            "engine": "offline",
        },
    )
    assert requests == ["/provider-sources/telegram/extract"]
    assert len(replies) == 1 and "Read from your screenshot" in replies[0]
    assert state == {"pending_signal_text": "EURUSD BUY SL 1.05 TP1 1.07"}
    assert not warnings


def check_malformed_pending_confirmation_fails_closed() -> None:
    """Legacy/corrupt pending user state can never be submitted as a signal."""
    replies = []
    calls = []

    async def connected(_update):
        return True

    async def broadcast(*_args, **_kwargs):
        calls.append("create")
        return "created"

    class Query:
        data = "SIGOK"

        async def answer(self):
            return None

        async def edit_message_text(self, message):
            replies.append(message)

    context = SimpleNamespace(user_data={"pending_signal_text": ["bad"], "awaiting_edit": True})
    update = SimpleNamespace(callback_query=Query())
    with (
        patch.object(handlers, "_can_submit_provider_signal", connected),
        patch.object(handlers, "_create_and_broadcast", broadcast),
    ):
        asyncio.run(handlers.on_signal_preview(update, context))
    assert len(replies) == 1 and "nothing to send" in replies[0].lower()
    assert calls == [], "Malformed user state reached signal creation"
    assert context.user_data == {}, "Malformed confirmation left pending state"


def check_hosted_legacy_provider_status_never_grants_identity() -> None:
    """Even a stale local-provider flag cannot claim hosted provider authority."""
    assert config.require_license is True
    replies = []
    calls = []

    async def disconnected(_user_id):
        return None

    async def register(path, **_kwargs):
        calls.append(("POST", path))
        return {"license_key": None}

    async def health(path, **_kwargs):
        calls.append(("GET", path))
        return {"admin_paused": True, "demo_only_mode": True}

    async def reply_text(message, **_kwargs):
        replies.append(message)

    user = SimpleNamespace(
        id=123456, username="offline-only", first_name="Test"
    )
    update = SimpleNamespace(
        effective_user=user,
        message=SimpleNamespace(reply_text=reply_text),
    )
    with (
        patch.object(config, "is_signal_provider", lambda _user_id: True),
        patch.object(config, "is_admin", lambda _user_id: False),
        patch.object(handlers, "_provider_source_status", disconnected),
        patch.object(handlers, "_backend_post", register),
        patch.object(handlers, "_backend_get", health),
    ):
        asyncio.run(handlers.start(update, None))
        asyncio.run(handlers.status(update, None))
        assert handlers._role_name(user.id) == "tester"

    assert calls == [
        ("POST", "/register_user"), ("GET", "/health"),
    ]
    assert len(replies) == 2
    assert "demo tester registered" in replies[0]
    assert "Provider Portal" in replies[0]
    assert "/connectprovider TOKEN" in replies[0]
    assert "screenshot provider ready" not in replies[0].lower()
    assert "Role: tester" in replies[1]
    assert "Provider Portal" in replies[1]
    assert "Role: screenshot provider" not in replies[1]


def check_connectprovider_error_does_not_echo_backend_secrets() -> None:
    """Backend error detail is untrusted and cannot enter Telegram replies."""
    secret = "SYNTHETIC_BACKEND_SECRET_DO_NOT_ECHO"
    replies = []
    calls = []

    async def reply_text(message, **_kwargs):
        replies.append(message)

    async def failed_connection(path, **kwargs):
        calls.append((path, kwargs.get("json", {}).get("connection_token")))
        return {"detail": f"internal token dump: {secret}"}

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123456),
        message=SimpleNamespace(reply_text=reply_text),
    )
    context = SimpleNamespace(args=["SYNTHETIC-ONE-TIME-TOKEN"])
    with patch.object(handlers, "_backend_post", failed_connection):
        asyncio.run(handlers.connect_provider_source(update, context))
    assert calls == [
        ("/provider-sources/telegram/connect", "SYNTHETIC-ONE-TIME-TOKEN")
    ]
    assert len(replies) == 1
    assert "not connected" in replies[0].lower()
    assert "Provider Portal" in replies[0]
    assert secret not in replies[0]
    assert "SYNTHETIC-ONE-TIME-TOKEN" not in replies[0]

def main() -> int:
    assert config.require_license is True, "Hosted-mode test failed to set boundary"
    app = build_application()  # Builder only: no initialize()/run_polling()/network

    all_handlers = [item for group in app.handlers.values() for item in group]
    commands = set()
    for handler in all_handlers:
        if isinstance(handler, CommandHandler):
            commands.update(handler.commands)

    mandatory = {
        "start", "join", "connectprovider", "status", "settings",
        "screenshothelp", "testsignal", "pause", "resume", "users",
        "lastsignals", "lastcommands",
    }
    missing = mandatory - commands
    assert not missing, f"Required hosted commands missing: {sorted(missing)}"
    assert "provider" not in commands, "Legacy shared-provider enrolment enabled in hosted bot"

    callback_patterns = [
        h.pattern for h in all_handlers
        if isinstance(h, CallbackQueryHandler) and h.pattern is not None
    ]
    assert any(
        p.match("YES:CMD-TEST") and p.match("NO:CMD-TEST")
        for p in callback_patterns
    ), "Explicit YES/NO subscriber approval callback missing"
    assert any(
        p.match("SIGOK") and p.match("SIGEDIT") and p.match("SIGNO")
        for p in callback_patterns
    ), "Provider screenshot preview/confirm/edit/cancel callbacks missing"

    assert sum(isinstance(h, MessageHandler) for h in all_handlers) >= 3, (
        "Screenshot/photo/text handler routing incomplete"
    )
    check_backend_http_fail_closed()
    check_unconfirmed_decision_does_not_claim_approval()
    check_screenshot_extraction_fail_closed()
    check_malformed_pending_confirmation_fails_closed()
    check_hosted_legacy_provider_status_never_grants_identity()
    check_connectprovider_error_does_not_echo_backend_secrets()
    print("Hosted Telegram bot: offline wiring and backend-error safety PASS; no external calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
