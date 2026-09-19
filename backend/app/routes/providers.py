"""Provider Edition tenancy and provisioning endpoints."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import (
    DemoTenantOut,
    FeedCreate,
    FeedOut,
    FeedPolicyUpdate,
    OrganizationCreate,
    ProviderBrandingUpdate,
    ProviderCreate,
    ProviderCredentialCreate,
    ProviderCredentialOut,
    ProviderOut,
    ProviderOverview,
    SignalOut,
    SubscriptionAcceptanceOut,
    SubscriptionCreate,
    SubscriptionInviteAccept,
    SubscriptionInviteCreate,
    SubscriptionInviteOut,
    SubscriptionOut,
)
from ..security import (
    ProviderPrincipal,
    require_admin,
    require_provider_principal,
    require_registration,
)

router = APIRouter(tags=["providers"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/provider-portal", response_class=HTMLResponse, include_in_schema=False)
def provider_portal() -> HTMLResponse:
    path = Path(__file__).resolve().parents[1] / "provider_portal.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


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
        feed = crud.create_feed(
            db,
            provider,
            payload.name,
            payload.source_namespace,
            paused=payload.paused,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return FeedOut.model_validate(feed)


@router.post("/admin/demo-tenant", response_model=DemoTenantOut)
def admin_demo_tenant(
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DemoTenantOut:
    bundle = crud.bootstrap_demo_tenant(db)
    db.commit()
    return DemoTenantOut(
        provider_id=bundle["provider"].id,
        provider_api_key=bundle["provider_api_key"],
        feed_id=bundle["feed"].id,
        user_id=bundle["user"].id,
        telegram_user_id=bundle["user"].telegram_user_id,
        license_key=bundle["license_key"],
    )


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


@router.get("/providers/me/overview", response_model=ProviderOverview)
def provider_overview(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderOverview:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    counts = crud.provider_overview(db, principal.provider_id)
    return ProviderOverview(provider=ProviderOut.model_validate(provider), **counts)


@router.put("/providers/me/branding", response_model=ProviderOut)
def provider_branding(
    payload: ProviderBrandingUpdate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        provider = crud.update_provider_branding(
            db,
            provider,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return ProviderOut.model_validate(provider)


@router.get("/providers/me/history")
def provider_history(
    limit: int = 50,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> dict:
    if principal is None:
        return {"history": []}
    return {
        "history": crud.provider_history(
            db,
            principal.provider_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.get("/providers/me/export")
def provider_evidence_export(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Export only the authenticated provider's operating evidence."""
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    feeds = crud.list_provider_feeds(db, provider.id)
    feed_rows = []
    subscriber_ids: set[str] = set()
    for feed in feeds:
        users = crud.list_active_users_for_feed(db, provider.id, feed.id)
        subscribers = []
        for user in users:
            subscriber_ids.add(user.id)
            account = crud.get_trading_account(db, provider.id, user.id)
            subscribers.append(
                {
                    "user_id": user.id,
                    "telegram_user_id": user.telegram_user_id,
                    "telegram_username": user.telegram_username,
                    "first_name": user.first_name,
                    "status": user.status,
                    "account_id": account.id if account else None,
                    "account_status": account.status if account else None,
                }
            )
        feed_rows.append(
            {
                "id": feed.id,
                "name": feed.name,
                "source_namespace": feed.source_namespace,
                "status": feed.status,
                "paused": feed.paused,
                "allowed_symbols_json": feed.allowed_symbols_json,
                "expiry_minutes": feed.expiry_minutes,
                "default_lot_size": feed.default_lot_size,
                "subscribers": subscribers,
            }
        )

    source_bindings = crud.list_provider_source_bindings(db, provider.id)
    history = crud.provider_history(db, provider.id, limit=1000)
    signals = crud.list_provider_signals(db, provider.id, limit=1000)

    payload = {
        "schema": "signalgate-provider-evidence-v1",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "provider": {
            "id": provider.id,
            "organization_id": provider.organization_id,
            "name": provider.name,
            "slug": provider.slug,
            "status": provider.status,
            "paused": provider.paused,
            "brand_display_name": provider.brand_display_name,
            "support_contact": provider.support_contact,
        },
        "feeds": feed_rows,
        "source_bindings": [
            {
                "binding_id": row.id,
                "feed_id": row.feed_id,
                "source_type": row.source_type,
                "external_identity": row.external_identity,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in source_bindings
        ],
        "signals": [
            {
                "id": row.id,
                "feed_id": row.feed_id,
                "source": row.source,
                "source_message_id": row.source_message_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "entry_type": row.entry_type,
                "entry_price": row.entry_price,
                "initial_stop_loss": row.initial_stop_loss,
                "tp1": row.tp1,
                "tp2": row.tp2,
                "tp3": row.tp3,
                "parser_status": row.parser_status,
                "parser_error": row.parser_error,
                "status": row.status,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
            }
            for row in signals
        ],
        "history": history,
        "summary": {
            "feed_count": len(feeds),
            "active_subscriber_count": len(subscriber_ids),
            "signal_count_in_export": len(signals),
            "command_count_in_export": len(history),
        },
    }
    return JSONResponse(
        content=__import__("fastapi").encoders.jsonable_encoder(payload),
        headers={
            "Content-Disposition": (
                f'attachment; filename="signalgate-{provider.slug}-evidence.json"'
            )
        },
    )


@router.get("/providers/me/feeds", response_model=list[FeedOut])
def provider_feeds(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[FeedOut]:
    if principal is None:
        return []
    return [FeedOut.model_validate(row) for row in crud.list_provider_feeds(db, principal.provider_id)]


@router.post("/providers/me/feeds", response_model=FeedOut)
def provider_create_feed(
    payload: FeedCreate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> FeedOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    try:
        feed = crud.create_feed(
            db,
            provider,
            payload.name,
            payload.source_namespace,
            paused=payload.paused,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return FeedOut.model_validate(feed)


@router.put("/providers/me/feeds/{feed_id}", response_model=FeedOut)
def provider_update_feed(
    feed_id: str,
    payload: FeedPolicyUpdate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> FeedOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    feed = crud.get_feed_for_provider(db, principal.provider_id, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        feed = crud.update_feed_policy(
            db,
            feed,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return FeedOut.model_validate(feed)


@router.post("/providers/me/credentials/rotate", response_model=ProviderCredentialOut)
def provider_rotate_credential(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderCredentialOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    credential, raw_key = crud.rotate_provider_credential(db, provider)
    db.commit()
    return ProviderCredentialOut(
        provider_id=provider.id,
        credential_id=credential.id,
        api_key=raw_key,
        label=credential.label,
    )


@router.post("/providers/me/subscriptions", response_model=SubscriptionOut, deprecated=True)
def provider_direct_subscription_disabled(
    payload: SubscriptionCreate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
) -> SubscriptionOut:
    del payload, principal
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Direct provider enrolment is disabled. Create a subscription invite and have the subscriber accept it.",
    )


@router.post("/providers/me/subscription-invites", response_model=SubscriptionInviteOut)
def provider_create_subscription_invite(
    payload: SubscriptionInviteCreate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> SubscriptionInviteOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    feed = crud.get_feed_for_provider(db, principal.provider_id, payload.feed_id)
    if provider is None or feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        invite, raw_token = crud.create_subscription_invite(
            db,
            provider,
            feed,
            expires_minutes=payload.expires_minutes,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return SubscriptionInviteOut(
        invite_id=invite.id,
        feed_id=invite.feed_id,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_user_id=invite.accepted_user_id,
        invite_token=raw_token,
    )


@router.get("/providers/me/subscription-invites", response_model=list[SubscriptionInviteOut])
def provider_subscription_invites(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[SubscriptionInviteOut]:
    if principal is None:
        return []
    rows = crud.list_provider_subscription_invites(db, principal.provider_id)
    return [
        SubscriptionInviteOut(
            invite_id=row.id,
            feed_id=row.feed_id,
            status=row.status,
            expires_at=row.expires_at,
            accepted_user_id=row.accepted_user_id,
            invite_token=None,
        )
        for row in rows
    ]


@router.post(
    "/providers/me/subscription-invites/{invite_id}/revoke",
    response_model=SubscriptionInviteOut,
)
def provider_revoke_subscription_invite(
    invite_id: str,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> SubscriptionInviteOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    try:
        invite = crud.revoke_subscription_invite(
            db,
            principal.provider_id,
            invite_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return SubscriptionInviteOut(
        invite_id=invite.id,
        feed_id=invite.feed_id,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_user_id=invite.accepted_user_id,
        invite_token=None,
    )


@router.post("/subscriptions/accept", response_model=SubscriptionAcceptanceOut)
def subscriber_accept_subscription_invite(
    payload: SubscriptionInviteAccept,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> SubscriptionAcceptanceOut:
    try:
        _invite, subscription, account, provider, feed = crud.accept_subscription_invite(
            db,
            payload.invite_token,
            payload.telegram_user_id,
        )
    except ValueError as exc:
        # Expiry may intentionally mutate/audit the invite; preserve that receipt.
        db.commit()
        code = (
            status.HTTP_410_GONE
            if "expired" in str(exc).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    db.commit()
    return SubscriptionAcceptanceOut(
        subscription_id=subscription.id,
        account_id=account.id,
        provider_id=provider.id,
        provider_name=provider.name,
        provider_display_name=provider.brand_display_name,
        feed_id=feed.id,
        feed_name=feed.name,
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
