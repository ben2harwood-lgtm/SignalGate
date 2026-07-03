"""Simple auth dependencies for the local prototype.

EA endpoints require an X-EA-API-Key header matching EA_API_KEY.
Admin endpoints require an X-Admin-Id header that matches one of
ADMIN_TELEGRAM_IDS. Signal-provider endpoints accept either an admin id or a
limited X-Signal-Provider-Id matching SIGNAL_PROVIDER_TELEGRAM_IDS. This is
intentionally lightweight — enough for a local demo, not production-grade auth.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import get_settings

settings = get_settings()


def require_ea_api_key(x_ea_api_key: str = Header(default="")) -> str:
    if x_ea_api_key != settings.ea_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-EA-API-Key",
        )
    return x_ea_api_key


def require_admin(x_admin_id: str = Header(default="")) -> str:
    if not x_admin_id or x_admin_id not in settings.admin_telegram_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required (X-Admin-Id)",
        )
    return x_admin_id


def require_signal_provider(
    x_admin_id: str = Header(default=""),
    x_signal_provider_id: str = Header(default=""),
) -> str:
    """Allow admins or limited screenshot providers to create signal previews.

    Signal providers are intentionally narrower than admins: they can submit a
    screenshot, confirm extracted text, and trigger the normal trade-card
    broadcast. They cannot pause/resume trading or use admin reporting endpoints.
    """
    candidate = x_signal_provider_id or x_admin_id
    if not candidate or not settings.is_signal_provider(candidate):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signal provider privileges required",
        )
    return candidate
