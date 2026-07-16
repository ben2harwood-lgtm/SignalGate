"""Simple auth dependencies for the local prototype.

EA endpoints require an X-EA-API-Key header matching EA_API_KEY.
Admin endpoints require an X-Admin-Id header that matches one of
ADMIN_TELEGRAM_IDS. Signal-provider endpoints accept either an admin id or a
limited X-Signal-Provider-Id matching SIGNAL_PROVIDER_TELEGRAM_IDS. This is
intentionally lightweight — enough for a local demo, not production-grade auth.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_ea_api_key(x_ea_api_key: str = Header(default="")) -> str:
    settings = get_settings()
    # SAFETY: a blank configured key must fail CLOSED, not open. Otherwise
    # blanking EA_API_KEY in .env (a likely rotation mistake) would silently let
    # every EA endpoint accept requests with no key at all.
    expected = settings.ea_api_key or ""
    if not expected.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EA API key is not configured on the server",
        )
    # Constant-time comparison to avoid a timing side channel on the key.
    if not secrets.compare_digest(x_ea_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-EA-API-Key",
        )
    return x_ea_api_key


def require_admin(
    x_admin_id: str = Header(default=""),
    x_admin_token: str = Header(default=""),
) -> str:
    """Authorise an admin request.

    HOSTED: when ADMIN_API_TOKEN is configured it is the ONLY accepted
    credential — a long random secret compared in constant time. The
    Telegram-id header is ignored for authz, because a Telegram id is public
    and trivially spoofable; it must never grant admin on a public server.

    LOCAL: with no token configured, fall back to the X-Admin-Id allowlist so
    the local demo and tests keep working unchanged.
    """
    settings = get_settings()
    token = settings.admin_api_token or ""
    if token.strip():
        if not secrets.compare_digest(x_admin_token, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-Admin-Token",
            )
        return "admin-token"
    # Local fallback (no real token configured).
    if not x_admin_id or x_admin_id not in settings.admin_telegram_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required (X-Admin-Id)",
        )
    return x_admin_id


def require_bot(x_bot_secret: str = Header(default="")) -> str:
    """Authenticate the Telegram bot to the backend.

    Gates the endpoints the bot proxies on behalf of end users (approve,
    reject, register, user lookup). When BOT_BACKEND_SECRET is configured it is
    required and compared in constant time, so a public server can't be driven
    by anyone who merely knows a Telegram id. Unset (local/tests) = allowed,
    preserving current behaviour.
    """
    settings = get_settings()
    expected = settings.bot_backend_secret or ""
    if not expected.strip():
        return "local"
    if not secrets.compare_digest(x_bot_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Bot-Secret",
        )
    return "bot"


def require_signal_provider(
    x_admin_id: str = Header(default=""),
    x_signal_provider_id: str = Header(default=""),
) -> str:
    """Allow admins or limited screenshot providers to create signal previews.

    Signal providers are intentionally narrower than admins: they can submit a
    screenshot, confirm extracted text, and trigger the normal trade-card
    broadcast. They cannot pause/resume trading or use admin reporting endpoints.
    """
    settings = get_settings()
    candidate = x_signal_provider_id or x_admin_id
    if not candidate or not settings.is_signal_provider(candidate):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signal provider privileges required",
        )
    return candidate
