"""Provider Edition tenancy and provisioning endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import (
    FeedCreate,
    FeedOut,
    OrganizationCreate,
    ProviderCreate,
    ProviderCredentialCreate,
    ProviderCredentialOut,
    ProviderOut,
    SignalOut,
    SubscriptionCreate,
    SubscriptionOut,
)
from ..security import ProviderPrincipal, require_admin, require_provider_principal

router = APIRouter(tags=["providers"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/admin/organizations")
def admin_create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    try:
        row = crud.create_organization(db, payload.name, payload.slug)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return {"id": row.id, "name": row.name, "slug": row.slug, "status": row.status}


@router.post("/admin/providers", response_model=ProviderOut)
def admin_create_provider(
    payload: ProviderCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> ProviderOut:
    try:
        row = crud.create_provider(db, payload.organization_id, payload.name, payload.slug)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ProviderOut.model_validate(row)


@router.post("/admin/providers/{provider_id}/credentials", response_model=ProviderCredentialOut)
def admin_issue_provider_credential(
    provider_id: str,
    payload: ProviderCredentialCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> ProviderCredentialOut:
    provider = crud.get_provider(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        credential, raw_key = crud.issue_provider_credential(db, provider, payload.label)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ProviderCredentialOut(
        provider_id=provider.id,
        credential_id=credential.id,
        api_key=raw_key,
        label=credential.label,
    )


@router.post("/admin/providers/{provider_id}/feeds", response_model=FeedOut)
def admin_create_feed(
    provider_id: str,
    payload: FeedCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> FeedOut:
    provider = crud.get_provider(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        feed = crud.create_feed(db, provider, payload.name, payload.source_namespace)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return FeedOut.model_validate(feed)


@router.get("/providers/me", response_model=ProviderOut)
def provider_me(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderOut.model_validate(provider)


@router.get("/providers/me/feeds", response_model=list[FeedOut])
def provider_feeds(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[FeedOut]:
    if principal is None:
        return []
    return [FeedOut.model_validate(row) for row in crud.list_provider_feeds(db, principal.provider_id)]


@router.post("/providers/me/subscriptions", response_model=SubscriptionOut)
def provider_subscribe_user(
    payload: SubscriptionCreate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    feed = crud.get_feed_for_provider(db, principal.provider_id, payload.feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    user = crud.get_user_by_telegram(db, payload.telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Registered subscriber not found")
    provider = crud.get_provider(db, principal.provider_id)
    try:
        subscription, account = crud.subscribe_user_to_feed(db, provider, feed, user)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return SubscriptionOut(
        subscription_id=subscription.id,
        account_id=account.id,
        feed_id=subscription.feed_id,
        user_id=subscription.user_id,
        status=subscription.status,
    )


@router.get("/providers/me/subscribers")
def provider_subscribers(
    feed_id: str,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> dict:
    if principal is None:
        return {"subscribers": []}
    feed = crud.get_feed_for_provider(db, principal.provider_id, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    users = crud.list_active_users_for_feed(db, principal.provider_id, feed.id)
    return {
        "subscribers": [
            {
                "user_id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "telegram_username": user.telegram_username,
                "first_name": user.first_name,
            }
            for user in users
        ]
    }


@router.get("/providers/me/signals", response_model=list[SignalOut])
def provider_signals(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[SignalOut]:
    if principal is None:
        return []
    return [SignalOut.model_validate(row) for row in crud.list_provider_signals(db, principal.provider_id)]


@router.get("/providers/me/commands")
def provider_commands(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> dict:
    if principal is None:
        return {"commands": []}
    commands = crud.list_provider_commands(db, principal.provider_id)
    return {
        "commands": [
            {
                "id": row.id,
                "provider_id": row.provider_id,
                "feed_id": row.feed_id,
                "account_id": row.account_id,
                "signal_id": row.signal_id,
                "user_id": row.user_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "status": row.status,
                "created_at": row.created_at,
                "processed_at": row.processed_at,
            }
            for row in commands
        ]
    }


@router.post("/providers/me/pause", response_model=ProviderOut)
def provider_pause(
    paused: bool,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    provider = crud.set_provider_paused(db, provider, paused)
    db.commit()
    return ProviderOut.model_validate(provider)


@router.post("/providers/me/feeds/{feed_id}/pause", response_model=FeedOut)
def provider_feed_pause(
    feed_id: str,
    paused: bool,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> FeedOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    feed = crud.get_feed_for_provider(db, principal.provider_id, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    feed = crud.set_feed_paused(db, feed, paused)
    db.commit()
    return FeedOut.model_validate(feed)
