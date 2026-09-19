"""Authentication dependencies for SignalGate.

Local demo mode keeps the original lightweight identity headers so existing
offline/demo workflows keep working. Hosted mode (REQUIRE_LICENSE=true) adds
server-held API secrets and constant-time comparison. Telegram ids remain
identity labels; they are not treated as credentials in hosted mode.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .database import get_db

settings = get_settings()


def _matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate.encode(), expected.encode())


@dataclass(frozen=True)
class ProviderPrincipal:
    provider_id: str
    organization_id: str


def _provider_key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def require_provider_principal(
    x_provider_id: str = Header(default="", alias="X-Provider-Id"),
    x_provider_api_key: str = Header(default="", alias="X-Provider-API-Key"),
    x_admin_id: str = Header(default=""),
    x_admin_api_key: str = Header(default="", alias="X-Admin-API-Key"),
    x_signal_provider_id: str = Header(default=""),
    x_signal_provider_api_key: str = Header(default="", alias="X-Signal-Provider-API-Key"),
    db: Session = Depends(get_db),
) -> Optional[ProviderPrincipal]:
    """Authenticate one provider without allowing cross-tenant authority.

    Hosted mode requires a DB-backed provider credential. Local demo mode may
    use the historical admin/provider headers and returns no tenant principal.
    """
    if x_provider_id:
        provider = db.get(models.Provider, x_provider_id)
        if provider is None or provider.status != "ACTIVE":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid provider")
        presented = _provider_key_hash(x_provider_api_key) if x_provider_api_key else ""
        credentials = db.scalars(
            select(models.ProviderCredential).where(
                models.ProviderCredential.provider_id == provider.id,
                models.ProviderCredential.status == "ACTIVE",
            )
        ).all()
        if not presented or not any(
            secrets.compare_digest(presented, credential.key_hash)
            for credential in credentials
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing provider credential",
            )
        return ProviderPrincipal(
            provider_id=provider.id,
            organization_id=provider.organization_id,
        )

    if settings.require_license:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hosted provider requests require provider id and provider API key",
        )

    if x_admin_id and settings.is_admin(x_admin_id):
        return None
    if (
        x_signal_provider_id
        and x_signal_provider_id in settings.signal_provider_telegram_ids
    ):
        return None
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Signal provider privileges required",
    )


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
