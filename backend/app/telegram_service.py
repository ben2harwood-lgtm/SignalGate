"""Outbound Telegram notifications from the backend.

Used to confirm trade lifecycle events to the user/admin. This is best-effort:
if no bot token is configured, calls become no-ops so the backend still works
fully for local testing without Telegram.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger("signalgate.telegram")
settings = get_settings()

_API = "https://api.telegram.org/bot{token}/sendMessage"


def _enabled() -> bool:
    return bool(settings.telegram_bot_token) and settings.telegram_bot_token != "replace_me"


def send_message(chat_id: str, text: str) -> bool:
    """Send a Telegram message. Returns True on success, False otherwise.

    Never raises into the request path — notification failures must not break
    trade lifecycle recording.
    """
    if not _enabled():
        logger.debug("Telegram disabled; skipping message to %s: %s", chat_id, text)
        return False
    try:
        resp = httpx.post(
            _API.format(token=settings.telegram_bot_token),
            json={"chat_id": chat_id, "text": text},
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("Telegram send failed: %s", exc)
        return False


def notify_admins(text: str) -> None:
    for admin_id in settings.admin_telegram_ids:
        send_message(admin_id, text)


def notify_user_and_admins(user_chat_id: Optional[str], text: str) -> None:
    if user_chat_id:
        send_message(user_chat_id, text)
    notify_admins(text)
