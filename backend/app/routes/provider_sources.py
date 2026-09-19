"""Tenant-bound provider source connections.

Providers create one-time connection tokens. The Telegram bot consumes those
tokens through its server-held registration credential, then all provider-source
actions resolve to the persisted provider/feed binding.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import crud
from ..config import get_settings
from ..database import get_db
from ..parser import parse_signal
from ..schemas import (
    ExtractionResponse,
    ProviderSourceBindingOut,
    ProviderSourceConnect,
    ProviderSourceInviteCreate,
    ProviderSourceInviteOut,
    ProviderSourceSignalCreate,
    SignalOut,
)
from ..security import ProviderPrincipal, require_provider_principal, require_registration
from ..vision_extractor import get_extractor

router = APIRouter(tags=["provider-sources"])
settings = get_settings()
MAX_SIGNAL_IMAGE_BYTES = 5 * 1024 * 1024


def _provider_binding_out(
    binding,
    provider,
    feed,
) -> ProviderSourceBindingOut:
    return ProviderSourceBindingOut(
        binding_id=binding.id,
        provider_id=provider.id,
        provider_name=provider.name,
        provider_display_name=provider.brand_display_name,
        feed_id=feed.id,
        feed_name=feed.name,
        expiry_minutes=feed.expiry_minutes,
        source_type=binding.source_type,
        status=binding.status,
    )


@router.post(
    "/providers/me/source-invites",
    response_model=ProviderSourceInviteOut,
)
def provider_create_source_invite(
    payload: ProviderSourceInviteCreate,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderSourceInviteOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    provider = crud.get_provider(db, principal.provider_id)
    feed = crud.get_feed_for_provider(db, principal.provider_id, payload.feed_id)
    if provider is None or feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        invite, raw_token = crud.create_provider_source_invite(
            db,
            provider,
            feed,
            expires_minutes=payload.expires_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return ProviderSourceInviteOut(
        invite_id=invite.id,
        feed_id=invite.feed_id,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_telegram_user_id=invite.accepted_telegram_user_id,
        connection_token=raw_token,
    )


@router.get(
    "/providers/me/source-invites",
    response_model=list[ProviderSourceInviteOut],
)
def provider_source_invites(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[ProviderSourceInviteOut]:
    if principal is None:
        return []
    return [
        ProviderSourceInviteOut(
            invite_id=row.id,
            feed_id=row.feed_id,
            status=row.status,
            expires_at=row.expires_at,
            accepted_telegram_user_id=row.accepted_telegram_user_id,
            connection_token=None,
        )
        for row in crud.list_provider_source_invites(db, principal.provider_id)
    ]


@router.post(
    "/providers/me/source-invites/{invite_id}/revoke",
    response_model=ProviderSourceInviteOut,
)
def provider_revoke_source_invite(
    invite_id: str,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderSourceInviteOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    try:
        invite = crud.revoke_provider_source_invite(
            db,
            principal.provider_id,
            invite_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return ProviderSourceInviteOut(
        invite_id=invite.id,
        feed_id=invite.feed_id,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_telegram_user_id=invite.accepted_telegram_user_id,
        connection_token=None,
    )


@router.get(
    "/providers/me/source-bindings",
    response_model=list[ProviderSourceBindingOut],
)
def provider_source_bindings(
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> list[ProviderSourceBindingOut]:
    if principal is None:
        return []
    results: list[ProviderSourceBindingOut] = []
    for binding in crud.list_provider_source_bindings(db, principal.provider_id):
        provider = crud.get_provider(db, binding.provider_id)
        feed = crud.get_feed_for_provider(db, binding.provider_id, binding.feed_id)
        if provider is not None and feed is not None:
            results.append(_provider_binding_out(binding, provider, feed))
    return results


@router.post(
    "/providers/me/source-bindings/{binding_id}/revoke",
    response_model=ProviderSourceBindingOut,
)
def provider_revoke_source_binding(
    binding_id: str,
    principal: ProviderPrincipal = Depends(require_provider_principal),
    db: Session = Depends(get_db),
) -> ProviderSourceBindingOut:
    if principal is None:
        raise HTTPException(status_code=400, detail="Tenant principal required")
    try:
        binding = crud.revoke_provider_source_binding(
            db,
            principal.provider_id,
            binding_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    provider = crud.get_provider(db, binding.provider_id)
    feed = crud.get_feed_for_provider(db, binding.provider_id, binding.feed_id)
    db.commit()
    return _provider_binding_out(binding, provider, feed)


@router.post(
    "/provider-sources/telegram/connect",
    response_model=ProviderSourceBindingOut,
)
def connect_telegram_provider_source(
    payload: ProviderSourceConnect,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> ProviderSourceBindingOut:
    try:
        _invite, binding, provider, feed = crud.connect_telegram_provider_source(
            db,
            payload.connection_token,
            payload.telegram_user_id,
        )
    except ValueError as exc:
        db.commit()
        code = (
            status.HTTP_410_GONE
            if "expired" in str(exc).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    db.commit()
    return _provider_binding_out(binding, provider, feed)


@router.get(
    "/provider-sources/telegram/status",
    response_model=ProviderSourceBindingOut,
)
def telegram_provider_source_status(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> ProviderSourceBindingOut:
    resolved = crud.get_telegram_provider_source(db, telegram_user_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Telegram provider source not connected")
    binding, provider, feed = resolved
    return _provider_binding_out(binding, provider, feed)


@router.post(
    "/provider-sources/telegram/extract",
    response_model=ExtractionResponse,
)
def telegram_provider_source_extract(
    telegram_user_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> ExtractionResponse:
    resolved = crud.get_telegram_provider_source(db, telegram_user_id)
    if resolved is None:
        raise HTTPException(status_code=403, detail="Telegram provider source not connected")
    binding, provider, feed = resolved

    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Signal extraction accepts image uploads only",
        )
    image_bytes = file.file.read(MAX_SIGNAL_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_SIGNAL_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Signal image exceeds 5 MiB limit",
        )

    extractor = get_extractor()
    extracted = extractor.extract(
        image_bytes,
        mime=file.content_type or "image/png",
    )
    parsed = (
        parse_signal(
            extracted.raw_text,
            expiry_minutes=(
                feed.expiry_minutes
                or settings.default_signal_expiry_minutes
            ),
            allowed_symbols=crud.feed_allowed_symbols(feed),
        )
        if extracted.raw_text
        else None
    )
    crud.add_audit(
        db,
        "PROVIDER_SOURCE_IMAGE_EXTRACTED",
        "provider_source_binding",
        binding.id,
        {
            "provider_id": provider.id,
            "feed_id": feed.id,
            "engine": extracted.engine,
            "readable": extracted.readable,
            "confidence": extracted.confidence,
            "parser_status": parsed.parser_status if parsed else "REJECTED",
        },
    )
    db.commit()

    if parsed is None:
        return ExtractionResponse(
            engine=extracted.engine,
            readable=extracted.readable,
            confidence=extracted.confidence,
            notes=extracted.notes,
            extracted_text=extracted.raw_text,
            parser_status="REJECTED",
            parser_error="No readable signal text in image.",
        )
    return ExtractionResponse(
        engine=extracted.engine,
        readable=extracted.readable,
        confidence=extracted.confidence,
        notes=extracted.notes,
        extracted_text=extracted.raw_text,
        parser_status=parsed.parser_status,
        parser_error=parsed.parser_error,
        symbol=parsed.symbol,
        direction=parsed.direction,
        entry_type=parsed.entry_type,
        entry_price=parsed.entry_price,
        initial_stop_loss=parsed.initial_stop_loss,
        tp1=parsed.tp1,
        tp2=parsed.tp2,
        tp3=parsed.tp3,
    )


@router.post(
    "/provider-sources/telegram/signals",
    response_model=SignalOut,
)
def telegram_provider_source_signal(
    payload: ProviderSourceSignalCreate,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> SignalOut:
    resolved = crud.get_telegram_provider_source(db, payload.telegram_user_id)
    if resolved is None:
        raise HTTPException(status_code=403, detail="Telegram provider source not connected")
    binding, provider, feed = resolved
    try:
        signal = crud.create_signal(
            db,
            raw_text=payload.raw_text,
            source=f"TELEGRAM_BINDING:{binding.id}",
            source_message_id=payload.source_message_id,
            provider_id=provider.id,
            feed_id=feed.id,
        )
    except crud.SignalReplayConflict as exc:
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return SignalOut.model_validate(signal)


@router.get("/provider-sources/telegram/recipients")
def telegram_provider_source_recipients(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> dict:
    resolved = crud.get_telegram_provider_source(db, telegram_user_id)
    if resolved is None:
        raise HTTPException(status_code=403, detail="Telegram provider source not connected")
    _binding, provider, feed = resolved
    users = crud.list_active_users_for_feed(db, provider.id, feed.id)
    return {
        "recipients": [
            {
                "user_id": user.id,
                "telegram_user_id": user.telegram_user_id,
            }
            for user in users
            if user.telegram_user_id.lstrip("-").isdigit()
        ]
    }
