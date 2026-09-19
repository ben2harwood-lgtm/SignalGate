"""Tenant-scoped provider operations.

These endpoints never trust an organisation/feed id as authorization. The
provider credential resolves to one organisation server-side, then every feed
lookup is constrained to that organisation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..schemas import ProviderFeedOut, ProviderSubscriptionRequest
from ..security import ProviderPrincipal, require_signal_provider

router = APIRouter(tags=["provider"], prefix="/provider")


def _organization_id(principal: ProviderPrincipal) -> str:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant-scoped provider credential required",
        )
    return principal.organization_id


def _require_operator(principal: ProviderPrincipal) -> None:
    if not principal.can_operate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Provider OPERATOR role required",
        )


def _feed_or_404(
    db: Session, principal: ProviderPrincipal, feed_id: str
) -> models.ProviderFeed:
    feed = crud.get_provider_feed(db, _organization_id(principal), feed_id)
    if feed is None:
        # Deliberately 404 rather than revealing that another tenant owns it.
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


@router.get("/feeds", response_model=list[ProviderFeedOut])
def list_feeds(
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> list[ProviderFeedOut]:
    feeds = crud.list_provider_feeds(db, _organization_id(principal))
    db.commit()
    return [ProviderFeedOut.model_validate(feed) for feed in feeds]


@router.post("/feeds/{feed_id}/pause")
def pause_feed(
    feed_id: str,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    _require_operator(principal)
    feed = _feed_or_404(db, principal, feed_id)
    crud.set_provider_feed_paused(db, feed, True)
    db.commit()
    return {"status": "ok", "feed_id": feed.id, "paused": True}


@router.post("/feeds/{feed_id}/resume")
def resume_feed(
    feed_id: str,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    _require_operator(principal)
    feed = _feed_or_404(db, principal, feed_id)
    crud.set_provider_feed_paused(db, feed, False)
    db.commit()
    return {"status": "ok", "feed_id": feed.id, "paused": False}


@router.post("/feeds/{feed_id}/subscribers")
def subscribe_user(
    feed_id: str,
    payload: ProviderSubscriptionRequest,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    _require_operator(principal)
    feed = _feed_or_404(db, principal, feed_id)
    user = crud.get_user_by_telegram(db, payload.telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    subscription = crud.subscribe_user_to_feed(db, feed, user)
    db.commit()
    return {
        "status": "ACTIVE",
        "subscription_id": subscription.id,
        "feed_id": feed.id,
        "user_id": user.id,
    }


@router.delete("/feeds/{feed_id}/subscribers/{telegram_user_id}")
def unsubscribe_user(
    feed_id: str,
    telegram_user_id: str,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    _require_operator(principal)
    feed = _feed_or_404(db, principal, feed_id)
    user = crud.get_user_by_telegram(db, telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    subscription = crud.set_feed_subscription_status(db, feed, user, "INACTIVE")
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.commit()
    return {"status": "INACTIVE", "feed_id": feed.id, "user_id": user.id}


@router.get("/feeds/{feed_id}/subscribers")
def list_subscribers(
    feed_id: str,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    feed = _feed_or_404(db, principal, feed_id)
    users = crud.list_active_feed_users(db, feed.id)
    db.commit()
    return {
        "feed_id": feed.id,
        "subscribers": [
            {
                "user_id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "telegram_username": user.telegram_username,
            }
            for user in users
        ],
    }


@router.get("/feeds/{feed_id}/signals")
def list_feed_signals(
    feed_id: str,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    feed = _feed_or_404(db, principal, feed_id)
    signals = list(
        db.scalars(
            select(models.Signal)
            .where(models.Signal.feed_id == feed.id)
            .order_by(models.Signal.created_at.desc())
            .limit(100)
        ).all()
    )
    db.commit()
    return {
        "feed_id": feed.id,
        "signals": [
            {
                "id": signal.id,
                "source": signal.source,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "parser_status": signal.parser_status,
                "status": signal.status,
                "created_at": signal.created_at,
            }
            for signal in signals
        ],
    }
