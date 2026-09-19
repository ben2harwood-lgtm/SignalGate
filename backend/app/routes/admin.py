"""Admin endpoints: pause, resume, status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crud, models
from ..config import get_settings
from ..database import get_db
from ..schemas import (
    ProviderCredentialIssue,
    ProviderFeedCreate,
    ProviderOrganizationCreate,
)
from ..security import require_admin

router = APIRouter(tags=["admin"], prefix="/admin")
settings = get_settings()


def _get_user_or_404(db: Session, telegram_user_id: str) -> models.User:
    user = crud.get_user_by_telegram(db, telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/pause")
def pause(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    crud.set_setting(db, "admin_paused", "true")
    crud.add_audit(db, "ADMIN_PAUSE", "settings", "admin_paused")
    db.commit()
    return {"status": "ok", "admin_paused": True}


@router.post("/resume")
def resume(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    crud.set_setting(db, "admin_paused", "false")
    crud.add_audit(db, "ADMIN_RESUME", "settings", "admin_paused")
    db.commit()
    return {"status": "ok", "admin_paused": False}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    """List all customers with their status and license key."""
    users = crud.list_users(db)
    return {
        "users": [
            {
                "user_id": u.id,
                "telegram_user_id": u.telegram_user_id,
                "telegram_username": u.telegram_username,
                "status": u.status,
                "license_key": u.license_key,
            }
            for u in users
        ]
    }


@router.post("/users/{telegram_user_id}/issue_license")
def issue_license(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Issue (or rotate) a customer's license key. They paste this into the EA."""
    user = _get_user_or_404(db, telegram_user_id)
    key = crud.issue_license(db, user)
    db.commit()
    return {"user_id": user.id, "telegram_user_id": user.telegram_user_id, "license_key": key}


@router.post("/users/{telegram_user_id}/activate")
def activate_user(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Activate a customer so their EA starts receiving commands again."""
    user = _get_user_or_404(db, telegram_user_id)
    crud.set_user_status(db, user, "ACTIVE")
    db.commit()
    return {"user_id": user.id, "status": user.status}


@router.post("/users/{telegram_user_id}/deactivate")
def deactivate_user(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Deactivate a customer (e.g. subscription lapsed). Blocks command delivery."""
    user = _get_user_or_404(db, telegram_user_id)
    crud.set_user_status(db, user, "INACTIVE")
    db.commit()
    return {"user_id": user.id, "status": user.status}


@router.post("/provider_organizations")
def create_provider_organization(
    payload: ProviderOrganizationCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    org = crud.create_provider_organization(db, payload.name)
    db.commit()
    return {"organization_id": org.id, "name": org.name, "status": org.status}


@router.get("/provider_organizations")
def list_provider_organizations(
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    organizations = list(
        db.scalars(
            select(models.ProviderOrganization).order_by(
                models.ProviderOrganization.created_at.asc()
            )
        ).all()
    )
    return {
        "organizations": [
            {"organization_id": org.id, "name": org.name, "status": org.status}
            for org in organizations
        ]
    }


@router.post("/provider_organizations/{organization_id}/feeds")
def create_provider_feed(
    organization_id: str,
    payload: ProviderFeedCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    try:
        feed = crud.create_provider_feed(
            db,
            organization_id=organization_id,
            name=payload.name,
            source_namespace=payload.source_namespace,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {
        "feed_id": feed.id,
        "organization_id": feed.organization_id,
        "name": feed.name,
        "source_namespace": feed.source_namespace,
        "paused": feed.paused,
    }


@router.post("/provider_organizations/{organization_id}/credentials")
def issue_provider_credential(
    organization_id: str,
    payload: ProviderCredentialIssue,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    try:
        credential, secret = crud.issue_provider_credential(
            db, organization_id=organization_id, role=payload.role
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    # Secret is deliberately returned once and is never stored in plaintext.
    return {
        "credential_id": credential.id,
        "organization_id": credential.organization_id,
        "role": credential.role,
        "api_key": secret,
        "key_prefix": credential.key_prefix,
    }


@router.get("/status")
def status(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    all_settings = {
        s.key: s.value
        for s in db.scalars(select(models.Setting)).all()
    }
    return {
        "demo_only_mode": settings.demo_only_mode,
        "admin_paused": crud.is_admin_paused(db),
        "settings": all_settings,
        "counts": {
            "provider_organizations": count(models.ProviderOrganization),
            "provider_feeds": count(models.ProviderFeed),
            "feed_subscriptions": count(models.FeedSubscription),
            "users": count(models.User),
            "signals": count(models.Signal),
            "approvals": count(models.Approval),
            "commands": count(models.Command),
            "executions": count(models.Execution),
            "management_events": count(models.TradeManagementEvent),
            "ledger_rows": count(models.PerformanceLedger),
        },
    }
