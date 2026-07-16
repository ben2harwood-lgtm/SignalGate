"""User registration + lookup endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import RegisterUserRequest, UserOut
from ..security import require_bot

router = APIRouter(tags=["users"])


@router.post("/register_user", response_model=UserOut)
def register_user(
    payload: RegisterUserRequest,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_bot),
) -> UserOut:
    user = crud.register_user(
        db,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        first_name=payload.first_name,
    )
    db.commit()
    return UserOut.model_validate(user)


@router.get("/users/{telegram_user_id}", response_model=UserOut)
def get_user(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _bot: str = Depends(require_bot),
) -> UserOut:
    """Look up a registered user by Telegram id (used by the bot's /status).

    SECURITY: this returns the user's license_key, which is a hosted-mode
    credential. It is gated by require_bot so that on a public server only our
    bot (holding BOT_BACKEND_SECRET) can resolve a Telegram id to its key —
    otherwise anyone could harvest license keys by enumerating public ids.

    Read-only: unlike /register_user it never creates a row, so /status can
    honestly report 'not registered' instead of the old hardcoded 'yes'.
    """
    user = crud.get_user_by_telegram(db, telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not registered")
    return UserOut.model_validate(user)
