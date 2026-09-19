"""Liveness, health and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import crud
from ..config import get_settings
from ..database import get_db
from ..schemas import HealthResponse, ReadinessResponse, SimpleStatus

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/livez", response_model=SimpleStatus)
def liveness() -> SimpleStatus:
    """Process liveness only. Does not claim dependencies are healthy."""
    return SimpleStatus(status="ok")


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        demo_only_mode=settings.demo_only_mode,
        admin_paused=crud.is_admin_paused(db),
    )


@router.get("/readyz", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    """Readiness requires a working database round-trip."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return ReadinessResponse(status="ready", database="ok")
