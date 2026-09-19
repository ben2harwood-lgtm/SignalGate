"""Authentication dependencies for SignalGate.

Local demo mode keeps the original lightweight identity headers so existing
offline/demo workflows keep working. Hosted mode (REQUIRE_LICENSE=true) adds
server-held API secrets and constant-time comparison. Telegram ids remain
identity labels; they are not treated as credentials in hosted mode.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import crud
from .config import get_settings
from .database import get_db

settings = get_settings()


@dataclass(frozen=True)
class ProviderPrincipal:
    organization_id: Optional[str]
    role: str
    credential_id: Optional[str] = None
    is_admin: bool = False
    legacy_identity: Optional[str] = None

    @property
    def can_operate(self) -> bool:
        return self.is_admin or self.role == "OPERATOR"


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
    db: Session = Depends(get_db),
) -> ProviderPrincipal:
    """Authenticate a platform admin or a tenant-scoped provider credential.

    Hosted provider credentials are high-entropy secrets stored only as hashes
    and resolve to exactly one provider organisation. The legacy provider id +
    shared secret path is local-demo only.
    """
    if x_admin_id and settings.is_admin(x_admin_id):
        if settings.require_license and not _matches(
            x_admin_api_key, settings.admin_api_key
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin credential required",
            )
        return ProviderPrincipal(
            organization_id=None,
            role="ADMIN",
            is_admin=True,
            legacy_identity=x_admin_id,
        )

    if settings.require_license:
        credential = crud.resolve_provider_credential(db, x_signal_provider_api_key)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Valid provider credential required",
            )
        return ProviderPrincipal(
            organization_id=credential.organization_id,
            role=credential.role,
            credential_id=credential.id,
        )

    if (
        not x_signal_provider_id
        or x_signal_provider_id not in settings.signal_provider_telegram_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signal provider privileges required",
        )
    return ProviderPrincipal(
        organization_id=None,
        role="OPERATOR",
        legacy_identity=x_signal_provider_id,
    )

