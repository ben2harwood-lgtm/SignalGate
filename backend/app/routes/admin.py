"""Admin endpoints: pause, resume, status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crud, models
from ..config import get_settings
from ..database import get_db
from ..security import require_admin

router = APIRouter(tags=["admin"], prefix="/admin")
settings = get_settings()


def _get_user_or_404(db: Session, telegram_user_id: str) -> models.User:
    user = crud.get_user_by_telegram(db, telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/pause")
def pause(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    crud.set_setting(db, "admin_paused", "true")
    crud.add_audit(db, "ADMIN_PAUSE", "settings", "admin_paused")
    db.commit()
    return {"status": "ok", "admin_paused": True}


@router.post("/resume")
def resume(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    crud.set_setting(db, "admin_paused", "false")
    crud.add_audit(db, "ADMIN_RESUME", "settings", "admin_paused")
    db.commit()
    return {"status": "ok", "admin_paused": False}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    """List all customers with their status and license key."""
    users = crud.list_users(db)
    return {
        "users": [
            {
                "user_id": u.id,
                "telegram_user_id": u.telegram_user_id,
                "telegram_username": u.telegram_username,
                "status": u.status,
                "license_key": u.license_key,
            }
            for u in users
        ]
    }


@router.post("/users/{telegram_user_id}/issue_license")
def issue_license(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Issue (or rotate) a customer's license key. They paste this into the EA."""
    user = _get_user_or_404(db, telegram_user_id)
    key = crud.issue_license(db, user)
    db.commit()
    return {"user_id": user.id, "telegram_user_id": user.telegram_user_id, "license_key": key}


@router.post("/users/{telegram_user_id}/activate")
def activate_user(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Activate a customer so their EA starts receiving commands again."""
    user = _get_user_or_404(db, telegram_user_id)
    crud.set_user_status(db, user, "ACTIVE")
    db.commit()
    return {"user_id": user.id, "status": user.status}


@router.post("/users/{telegram_user_id}/deactivate")
def deactivate_user(
    telegram_user_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Deactivate a customer (e.g. subscription lapsed). Blocks command delivery."""
    user = _get_user_or_404(db, telegram_user_id)
    crud.set_user_status(db, user, "INACTIVE")
    db.commit()
    return {"user_id": user.id, "status": user.status}


@router.post("/commands/{command_id}/reset")
def reset_command(
    command_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Return a stuck command (SENT_TO_EA after an EA crash, or FAILED) to
    PENDING so it can be re-delivered. Refuses to reset a live or completed
    trade so a demo position can never be re-opened."""
    command = crud.get_command(db, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    try:
        crud.reset_command_to_pending(db, command)
    except crud.CommandStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    return {"command_id": command.id, "status": command.status}


@router.get("/status")
def status(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
) -> dict:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    all_settings = {
        s.key: s.value
        for s in db.scalars(select(models.Setting)).all()
    }
    return {
        "demo_only_mode": settings.demo_only_mode,
        "admin_paused": crud.is_admin_paused(db),
        "settings": all_settings,
        "counts": {
            "users": count(models.User),
            "signals": count(models.Signal),
            "approvals": count(models.Approval),
            "commands": count(models.Command),
            "executions": count(models.Execution),
            "management_events": count(models.TradeManagementEvent),
            "ledger_rows": count(models.PerformanceLedger),
        },
    }
