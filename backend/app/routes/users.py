"""User registration endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..schemas import RegisterUserRequest, UserOut

router = APIRouter(tags=["users"])


@router.post("/register_user", response_model=UserOut)
def register_user(
    payload: RegisterUserRequest, db: Session = Depends(get_db)
) -> UserOut:
    user = crud.register_user(
        db,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        first_name=payload.first_name,
    )
    db.commit()
    return UserOut.model_validate(user)
