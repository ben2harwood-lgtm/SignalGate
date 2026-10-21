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
    print("Hosted Telegram bot: offline wiring and backend-error safety PASS; no external calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
