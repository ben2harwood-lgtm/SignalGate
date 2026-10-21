#!/usr/bin/env python3
"""Offline smoke for hosted Telegram handler wiring; NEVER calls Telegram API.

Run in an isolated environment with telegram_bot/requirements.txt installed.
The bot and its handlers must be importable and register hosted commands without
any backend, broker, user account, internet access or real credentials.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

# Force synthetic credentials before importing config or instantiating the bot.
# This test must never pick up a developer's real token or hosted .env.
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:OFFLINE_TEST_ONLY"
os.environ["REQUIRE_LICENSE"] = "true"
os.environ["BACKEND_BASE_URL"] = "https://unreachable.example.invalid"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler  # noqa: E402
from bot import build_application  # noqa: E402
from config import config  # noqa: E402


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
    print("Hosted Telegram bot: offline wiring PASS; no messages, trades or network calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
