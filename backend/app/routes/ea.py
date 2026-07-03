"""EA heartbeat endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..config import get_settings
from ..database import get_db
from ..security import require_ea_api_key

router = APIRouter(tags=["ea"])
settings = get_settings()


@router.get("/ea/heartbeat")
def heartbeat(
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> dict:
    crud.add_audit(db, "EA_HEARTBEAT", "ea", None)
    db.commit()
    return {
        "status": "ok",
        "demo_only_mode": settings.demo_only_mode,
        "admin_paused": crud.is_admin_paused(db),
    }
