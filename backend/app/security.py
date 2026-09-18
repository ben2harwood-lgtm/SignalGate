"""Authentication dependencies for SignalGate.

Local demo mode keeps the original lightweight identity headers so existing
offline/demo workflows keep working. Hosted mode (REQUIRE_LICENSE=true) adds
server-held API secrets and constant-time comparison. Telegram ids remain
identity labels; they are not treated as credentials in hosted mode.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

settings = get_settings()


def _matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate.encode(), expected.encode())


def require_ea_api_key(x_ea_api_key: str = Header(default="")) -> str:
    if not _matches(x_ea_api_key, settings.ea_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-EA-API-Key",
        )
    return x_ea_api_key


def require_registration(
    x_registration_api_key: str = Header(default="", alias="X-Registration-API-Key"),
) -> str:
    """Authenticate the shared bot's hosted user/decision service calls.

    The header name is retained for backwards compatibility, but this credential
    protects both registration and subscriber YES/NO callbacks. Telegram ids are
    identity claims; this server-held secret is the credential. Local demo mode
    remains open to preserve the offline test flow.
    """
    if settings.require_license and not _matches(
        x_registration_api_key, settings.registration_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing registration credential",
        )
    return x_registration_api_key


def require_admin(
    x_admin_id: str = Header(default=""),
    x_admin_api_key: str = Header(default="", alias="X-Admin-API-Key"),
) -> str:
    if not x_admin_id or x_admin_id not in settings.admin_telegram_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required (X-Admin-Id)",
        )
    if settings.require_license and not _matches(
        x_admin_api_key, settings.admin_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin credential required",
        )
    return x_admin_id


def require_signal_provider(
    x_admin_id: str = Header(default=""),
    x_admin_api_key: str = Header(default="", alias="X-Admin-API-Key"),
    x_signal_provider_id: str = Header(default=""),
    x_signal_provider_api_key: str = Header(
        default="", alias="X-Signal-Provider-API-Key"
    ),
) -> str:
    """Allow an authenticated admin or a least-privilege signal provider."""
    if x_admin_id and settings.is_admin(x_admin_id):
        if settings.require_license and not _matches(
            x_admin_api_key, settings.admin_api_key
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin credential required",
            )
        return x_admin_id

    if (
        not x_signal_provider_id
        or x_signal_provider_id not in settings.signal_provider_telegram_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signal provider privileges required",
        )
    if settings.require_license and not _matches(
        x_signal_provider_api_key, settings.signal_provider_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signal provider credential required",
        )
    return x_signal_provider_id
