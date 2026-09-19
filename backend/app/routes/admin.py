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


@router.get("/ledger")
def ledger(
    limit: int = 20,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    """Read-only performance evidence. Wins, losses and uncertain outcomes remain visible."""
    rows = crud.recent_ledger(db, limit=max(1, min(limit, 200)))
    return {
        "count": len(rows),
        "ledger": [
            {
                "id": row.id,
                "signal_id": row.signal_id,
                "command_id": row.command_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "entry_price": row.entry_price,
                "initial_stop_loss": row.initial_stop_loss,
                "tp1": row.tp1,
                "tp2": row.tp2,
                "tp3": row.tp3,
                "result_status": row.result_status,
                "r_result": row.r_result,
                "slippage": row.slippage,
                "spread_at_execution": row.spread_at_execution,
                "final_notes": row.final_notes,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
    }


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
