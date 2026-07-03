"""EA-facing command endpoints: poll pending, ack received, report execution
and management events."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..models import Command
from ..schemas import (
    CommandOut,
    CommandReceivedRequest,
    ExecutionRequest,
    ManagementEventRequest,
    PendingCommandResponse,
    SimpleStatus,
    TakeProfitOut,
)
from ..security import require_ea_api_key
from ..telegram_service import notify_user_and_admins

router = APIRouter(tags=["commands"])


def serialize_command(command: Command) -> CommandOut:
    """Build the structured EA command payload (the only data MT5 ever sees)."""
    take_profits = []
    if command.tp1 is not None:
        take_profits.append(
            TakeProfitOut(
                level=1,
                price=command.tp1,
                close_percent=command.tp1_close_percent,
                lot=command.tp1_lot,
                move_sl_to="BREAKEVEN",
            )
        )
    if command.tp2 is not None:
        take_profits.append(
            TakeProfitOut(
                level=2,
                price=command.tp2,
                close_percent=command.tp2_close_percent,
                lot=command.tp2_lot,
                move_sl_to="TP1",
            )
        )
    if command.tp3 is not None:
        take_profits.append(
            TakeProfitOut(
                level=3,
                price=command.tp3,
                close_percent=command.tp3_close_percent,
                lot=command.tp3_lot,
                move_sl_to=None,
            )
        )
    return CommandOut(
        command_id=command.id,
        signal_id=command.signal_id,
        approval_id=command.approval_id,
        user_id=command.user_id,
        symbol=command.symbol,
        direction=command.direction,
        entry_type=command.entry_type,
        entry_price=command.entry_price,
        initial_stop_loss=command.initial_stop_loss,
        take_profits=take_profits,
        lot_size=command.lot_size,
        split_ticket_demo_partial_mode=command.split_ticket_demo_partial_mode,
        expires_at=command.expires_at,
        demo_only=True,
    )


def _get_command_or_404(db: Session, command_id: str) -> Command:
    command = crud.get_command(db, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return command


@router.get("/commands/pending", response_model=PendingCommandResponse)
def pending_command(
    user_id: Optional[str] = None,
    license_key: Optional[str] = None,
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> PendingCommandResponse:
    # Resolve which customer this EA poll belongs to. In the hosted model the
    # license key is authoritative; locally we fall back to user_id. An EA for
    # an unknown/inactive/unlicensed customer simply gets no command.
    user = crud.resolve_ea_user(db, user_id=user_id, license_key=license_key)
    if user is None:
        db.commit()
        return PendingCommandResponse(command=None)
    command = crud.get_pending_command_for_user(db, user.id)
    db.commit()
    if command is None:
        return PendingCommandResponse(command=None)
    return PendingCommandResponse(command=serialize_command(command))


@router.post("/commands/{command_id}/received", response_model=SimpleStatus)
def command_received(
    command_id: str,
    payload: CommandReceivedRequest,
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_command_or_404(db, command_id)
    crud.mark_command_received(db, command)
    db.commit()
    return SimpleStatus(status="received")


@router.post("/commands/{command_id}/execution", response_model=SimpleStatus)
def report_execution(
    command_id: str,
    payload: ExecutionRequest,
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_command_or_404(db, command_id)
    execution = crud.record_execution(db, command, payload)
    db.commit()

    user = db.get(crud.models.User, command.user_id)
    chat_id = user.telegram_user_id if user else None
    if execution.status == "SUCCESS":
        notify_user_and_admins(
            chat_id,
            f"✅ Demo trade OPENED for {command.symbol} {command.direction} "
            f"(command {command.id}). Demo only.",
        )
    else:
        notify_user_and_admins(
            chat_id,
            f"⚠️ Demo trade FAILED for {command.symbol} {command.direction} "
            f"(command {command.id}): {execution.error_code or ''} "
            f"{execution.error_message or ''}".strip(),
        )
    return SimpleStatus(status="ok")


# Management events that warrant a Telegram confirmation to user/admin.
_NOTIFY_EVENTS = {
    "TP1_CLOSE_SUCCESS": "🎯 TP1 hit. Remaining SL moved to breakeven.",
    "TP2_CLOSE_SUCCESS": "🎯 TP2 hit. Remaining SL moved to TP1.",
    "TP3_CLOSE_SUCCESS": "🎯 TP3 hit. Final child closed.",
    "FULLY_CLOSED": "🏁 Trade fully closed.",
    "STOP_LOSS_HIT": "🛑 Stop loss hit.",
    "FAILED_MANAGEMENT": "⚠️ Trade management failure reported.",
}


@router.post("/commands/{command_id}/management_event", response_model=SimpleStatus)
def report_management_event(
    command_id: str,
    payload: ManagementEventRequest,
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_command_or_404(db, command_id)
    crud.record_management_event(db, command, payload)
    db.commit()

    note = _NOTIFY_EVENTS.get(payload.event_type)
    if note:
        user = db.get(crud.models.User, command.user_id)
        chat_id = user.telegram_user_id if user else None
        notify_user_and_admins(
            chat_id, f"{note} ({command.symbol} {command.direction}, {command.id})"
        )
    return SimpleStatus(status="ok")
