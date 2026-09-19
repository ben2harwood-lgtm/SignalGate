"""Signal creation, listing, and approve/reject decision endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import crud
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
    require_provider_principal,
    require_registration,
)
from ..vision_extractor import get_extractor

router = APIRouter(tags=["signals"])
MAX_SIGNAL_IMAGE_BYTES = 5 * 1024 * 1024


@router.post("/signals/extract", response_model=ExtractionResponse)
def extract_signal(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _provider: Optional[ProviderPrincipal] = Depends(require_provider_principal),
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
    _provider: str = Depends(require_signal_provider),
) -> SignalOut:
    try:
        signal = crud.create_signal(
            db,
            raw_text=payload.raw_text,
            source=payload.source,
            source_message_id=payload.source_message_id,
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
    db: Session = Depends(get_db),
    _provider: str = Depends(require_signal_provider),
) -> dict:
    """Return active Telegram recipients for trade-card broadcast.

    This endpoint is for the bot, not a dashboard. It keeps screenshot providers
    out of admin endpoints while still letting a confirmed signal reach testers.
    """
    users = crud.list_active_users(db)
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
