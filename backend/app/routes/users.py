"""User registration endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import RegisterUserRequest, UserOut
from ..security import require_registration

router = APIRouter(tags=["users"])


@router.post("/register_user", response_model=UserOut)
def register_user(
    payload: RegisterUserRequest,
    db: Session = Depends(get_db),
    _registration: str = Depends(require_registration),
) -> UserOut:
    user = crud.register_user(
        db,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        first_name=payload.first_name,
    )
    issued = getattr(user, "_issued_license_key", None)
    db.commit()
    return UserOut(
        id=user.id,
        telegram_user_id=user.telegram_user_id,
        telegram_username=user.telegram_username,
        first_name=user.first_name,
        status=user.status,
        fixed_lot_size=user.fixed_lot_size,
        license_key=issued,
        license_key_last4=user.license_key_last4,
    )
