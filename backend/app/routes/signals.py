"""Signal creation, listing, and approve/reject decision endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import crud
from ..config import get_settings
from ..database import get_db
from ..parser import parse_signal
from ..schemas import (
    CreateSignalRequest,
    DecisionRequest,
    DecisionResponse,
    ExtractionResponse,
    SignalOut,
)
from ..security import (
    ProviderPrincipal,
    require_admin,
    require_registration,
    require_signal_provider,
)
from ..vision_extractor import get_extractor

router = APIRouter(tags=["signals"])
settings = get_settings()
MAX_SIGNAL_IMAGE_BYTES = 5 * 1024 * 1024


@router.post("/signals/extract", response_model=ExtractionResponse)
def extract_signal(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _provider: ProviderPrincipal = Depends(require_signal_provider),
) -> ExtractionResponse:
    """Read a signal screenshot into structured fields for human confirmation.

    SAFETY: this only PREVIEWS. It runs the image through the vision extractor to
    get candidate text, then through the deterministic parser. It does NOT create
    a signal or broadcast anything — the bot shows this to the provider to
    confirm/edit, and only then calls /signals/create.
    """
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Signal extraction accepts image uploads only",
        )
    image_bytes = file.file.read(MAX_SIGNAL_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_SIGNAL_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Signal image exceeds 5 MiB limit",
        )
    extractor = get_extractor()
    extracted = extractor.extract(image_bytes, mime=file.content_type or "image/png")

    parsed = parse_signal(extracted.raw_text) if extracted.raw_text else None
    crud.add_audit(
        db,
        "SIGNAL_IMAGE_EXTRACTED",
        "signal",
        None,
        {
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


@router.post("/signals/create", response_model=SignalOut)
def create_signal(
    payload: CreateSignalRequest,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> SignalOut:
    feed_id = None
    source = payload.source
    if principal.organization_id is not None:
        feed = crud.get_provider_feed_by_source(
            db, principal.organization_id, payload.source
        )
        if feed is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Signal source is not assigned to this provider tenant",
            )
        if feed.status != "ACTIVE" or feed.paused:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Provider feed is inactive or paused",
            )
        feed_id = feed.id
        # Never persist a provider-controlled alternate namespace in hosted mode.
        source = feed.source_namespace
    elif settings.require_license:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hosted signal creation requires a tenant-scoped provider credential",
        )

    try:
        signal = crud.create_signal(
            db,
            raw_text=payload.raw_text,
            source=source,
            source_message_id=payload.source_message_id,
            feed_id=feed_id,
        )
    except crud.SignalReplayConflict as exc:
        # Persist the conflict audit receipt, but never pretend the new content
        # was accepted as the previously stored signal.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    db.commit()
    return SignalOut.model_validate(signal)


@router.get("/signals/recipients")
def signal_recipients(
    signal_id: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: ProviderPrincipal = Depends(require_signal_provider),
) -> dict:
    """Return recipients without allowing cross-tenant subscriber enumeration."""
    if principal.organization_id is not None:
        if not signal_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="signal_id is required for tenant-scoped recipient lookup",
            )
        signal = crud.get_signal(db, signal_id)
        if signal is None or signal.feed_id is None:
            raise HTTPException(status_code=404, detail="Signal not found")
        feed = crud.get_provider_feed(
            db, principal.organization_id, signal.feed_id
        )
        if feed is None:
            raise HTTPException(status_code=404, detail="Signal not found")
        users = crud.list_active_feed_users(db, feed.id)
    else:
        if settings.require_license:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant-scoped provider credential required",
            )
        # Local demo compatibility: unscoped signals still broadcast to all
        # active test users.
        users = crud.list_active_users(db)

    db.commit()
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


@router.get("/signals/recent", response_model=List[SignalOut])
def recent_signals(
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> List[SignalOut]:
    signals = crud.recent_signals(db)
    return [SignalOut.model_validate(s) for s in signals]


@router.post("/signals/{signal_id}/approve", response_model=DecisionResponse)
def approve(
    signal_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> DecisionResponse:
    result = crud.approve_signal(db, signal_id, payload.telegram_user_id)
    db.commit()
    return DecisionResponse(**result)


@router.post("/signals/{signal_id}/reject", response_model=DecisionResponse)
def reject(
    signal_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_registration),
) -> DecisionResponse:
    result = crud.reject_signal(db, signal_id, payload.telegram_user_id)
    db.commit()
    return DecisionResponse(**result)
