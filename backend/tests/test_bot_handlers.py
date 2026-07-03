"""Telegram bot handler tests (P1-9: the bot module had zero tests).

Verifies the onboarding fixes: /start always registers and shows the backend
UserID (P0-7/P1-22), /start is honest when the backend is down (P1-21), and
/status reports real registration state instead of a hardcoded 'yes' (P1-9).

Skipped automatically if python-telegram-bot is not installed.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")  # skip cleanly if the bot dep is absent

# Make the telegram_bot package importable and ensure it sees an admin id
# (so we exercise the admin/provider path that previously skipped registration).
_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT = os.path.abspath(os.path.join(_HERE, "..", "..", "telegram_bot"))
sys.path.insert(0, _BOT)
os.environ.setdefault("ADMIN_TELEGRAM_IDS", "999")

import handlers  # noqa: E402


def _fake_update(user_id=999, username="ben", first_name="Ben"):
    update = SimpleNamespace()
    update.effective_user = SimpleNamespace(
        id=user_id, username=username, first_name=first_name
    )
    update.message = SimpleNamespace(reply_text=AsyncMock())
    return update


async def test_start_registers_admin_and_shows_user_id(monkeypatch):
    """An admin/provider must still be registered and told their EA UserID."""
    captured = {}

    async def fake_post(path, **kwargs):
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return {"id": "USER-000001", "status": "ACTIVE"}

    monkeypatch.setattr(handlers, "_backend_post", fake_post)
    update = _fake_update(user_id=999)  # 999 is admin in the test env

    await handlers.start(update, None)

    assert captured["path"] == "/register_user"  # registration DID happen
    reply = update.message.reply_text.call_args[0][0]
    assert "USER-000001" in reply
    assert "registered" in reply.lower()


async def test_start_honest_when_backend_down(monkeypatch):
    async def fake_post(path, **kwargs):
        return None  # backend unreachable

    monkeypatch.setattr(handlers, "_backend_post", fake_post)
    update = _fake_update()

    await handlers.start(update, None)

    reply = update.message.reply_text.call_args[0][0]
    assert "could not reach" in reply.lower()
    assert "registered" not in reply.lower().replace("register you", "")


async def test_status_reports_unregistered(monkeypatch):
    async def fake_get(path, **kwargs):
        if path == "/health":
            return {"demo_only_mode": True, "admin_paused": False}
        return {"detail": "User not registered"}  # /users/{id} -> 404 body

    monkeypatch.setattr(handlers, "_backend_get", fake_get)
    update = _fake_update()

    await handlers.status(update, None)

    reply = update.message.reply_text.call_args[0][0]
    assert "Registered: no" in reply


async def test_status_reports_registered_with_id(monkeypatch):
    async def fake_get(path, **kwargs):
        if path == "/health":
            return {"demo_only_mode": True, "admin_paused": False}
        return {"id": "USER-000007", "status": "ACTIVE"}

    monkeypatch.setattr(handlers, "_backend_get", fake_get)
    update = _fake_update()

    await handlers.status(update, None)

    reply = update.message.reply_text.call_args[0][0]
    assert "Registered: yes" in reply
    assert "USER-000007" in reply
