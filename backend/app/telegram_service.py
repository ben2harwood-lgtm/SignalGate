"""Best-effort backend Telegram notifications with secret-free diagnostics.

A send failure must never interrupt trade lifecycle recording. Logs never
include the bot credential (embedded in the HTTP URL), chat identity or message.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger("signalgate.telegram")
# httpx INFO emits full request URLs; Telegram embeds the bot credential in
# its API URL path. Suppress the library's URL-bearing request logs globally.
logging.getLogger("httpx").setLevel(logging.WARNING)
settings = get_settings()

_API = "https://api.telegram.org/bot{token}/sendMessage"


def _enabled() -> bool:
    return bool(settings.telegram_bot_token) and settings.telegram_bot_token != "replace_me"


def send_message(chat_id: str, text: str) -> bool:
    """Send a Telegram notification, returning False on any delivery failure.

    No transport URL, exception details, chat id or message text enter logs.
    """
    if not _enabled():
        logger.debug("Telegram notification disabled; send skipped")
        return False
    try:
        resp = httpx.post(
            _API.format(token=settings.telegram_bot_token),
            json={"chat_id": chat_id, "text": text},
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 - notification failure must not break request
        logger.warning("Telegram notification failed (transport or client error)")
        return False


def notify_admins(text: str) -> None:
    for admin_id in settings.admin_telegram_ids:
        send_message(admin_id, text)


def notify_user_and_admins(user_chat_id: Optional[str], text: str) -> None:
    if user_chat_id:
        send_message(user_chat_id, text)
    notify_admins(text)
