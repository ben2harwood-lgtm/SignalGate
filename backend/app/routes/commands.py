"""EA-facing command endpoints: poll, acknowledge and report lifecycle events."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crud
from ..config import get_settings
from ..database import get_db
from ..models import Command
from ..schemas import (
    BrokerPositionReconcileRequest,
    BrokerPositionReconcileResponse,
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
settings = get_settings()


def serialize_command(command: Command) -> CommandOut:
    """Build the structured EA command payload (the only data MT5 ever sees)."""
    take_profits = []
    if command.tp1 is not None:
        take_profits.append(TakeProfitOut(level=1, price=command.tp1, close_percent=command.tp1_close_percent, lot=command.tp1_lot, move_sl_to="BREAKEVEN"))
    if command.tp2 is not None:
        take_profits.append(TakeProfitOut(level=2, price=command.tp2, close_percent=command.tp2_close_percent, lot=command.tp2_lot, move_sl_to="TP1"))
    if command.tp3 is not None:
        take_profits.append(TakeProfitOut(level=3, price=command.tp3, close_percent=command.tp3_close_percent, lot=command.tp3_lot, move_sl_to=None))
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


def _get_authorized_callback_command(
    db: Session, command_id: str, license_key: str
) -> Command:
    """Deny unowned and absent hosted command IDs with the same response.

    A shared EA API key is not customer authority. Resolve the current licence
    before command lookup; neither revoked credentials nor another tenant may
    learn whether an opaque command ID exists. The local demo retains 404 for
    unknown commands without adding hosted authentication shortcuts.
    """
    if not settings.require_license:
        return _get_command_or_404(db, command_id)

    user = crud.resolve_ea_user(db, license_key=license_key)
    if user is None:
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )

    # Serialize hosted callbacks with licence rotation/deactivation on PostgreSQL.
    # Holding a shared User lock through the route's existing commit prevents
    # a once-valid EA licence from recording state *after* revocation commits.
    # The predicate is rechecked after any concurrent row lock wait.
    customer_query = select(crud.models.User).where(
        crud.models.User.id == user.id,
        crud.models.User.status == "ACTIVE",
        crud.models.User.license_key_hash == crud.hash_license_key(license_key),
    )
    if db.get_bind().dialect.name == "postgresql":
        customer_query = customer_query.with_for_update(read=True)
    if db.scalar(customer_query.execution_options(populate_existing=True)) is None:
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )

    command = db.scalar(
        select(Command).where(Command.id == command_id, Command.user_id == user.id)
    )
    if command is None:
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )
    return command


@router.get("/commands/pending", response_model=PendingCommandResponse)
def pending_command(
    user_id: Optional[str] = None,
    license_key: Optional[str] = None,
    x_sg_license_key: str = Header(default="", alias="X-SG-License-Key"),
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> PendingCommandResponse:
    # Hosted mode accepts the licence only in a header so it is not leaked into
    # URLs/proxy logs. Query-string licence support remains local-demo only.
    presented_license = x_sg_license_key or (
        license_key if not settings.require_license else None
    )
    user = crud.resolve_ea_user(
        db, user_id=user_id, license_key=presented_license
    )
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
    x_sg_license_key: str = Header(default="", alias="X-SG-License-Key"),
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_authorized_callback_command(db, command_id, x_sg_license_key)
    crud.mark_command_received(db, command)
    db.commit()
    return SimpleStatus(status="received")


@router.post("/commands/{command_id}/execution", response_model=SimpleStatus)
def report_execution(
    command_id: str,
    payload: ExecutionRequest,
    x_sg_license_key: str = Header(default="", alias="X-SG-License-Key"),
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_authorized_callback_command(db, command_id, x_sg_license_key)
    try:
        execution, created = crud.record_execution(db, command, payload)
    except crud.ExecutionReportConflict as exc:
        # Keep the conflict audit receipt. The incoming callback does not alter
        # execution or command state.
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()

    if not created:
        return SimpleStatus(status="duplicate_ignored")

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


@router.post(
    "/commands/{command_id}/reconcile_open_position",
    response_model=BrokerPositionReconcileResponse,
)
def reconcile_open_position(
    command_id: str,
    payload: BrokerPositionReconcileRequest,
    x_sg_license_key: str = Header(default="", alias="X-SG-License-Key"),
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> BrokerPositionReconcileResponse:
    command = _get_authorized_callback_command(db, command_id, x_sg_license_key)
    try:
        execution, reconciliation_status = crud.reconcile_open_position(
            db, command, payload
        )
    except crud.BrokerReconciliationConflict as exc:
        # Persist the discrepancy receipt. Never mutate an execution to make
        # contradictory broker state fit.
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return BrokerPositionReconcileResponse(
        status=reconciliation_status,
        execution_id=execution.id,
        command_status=command.status,
    )


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
    x_sg_license_key: str = Header(default="", alias="X-SG-License-Key"),
    db: Session = Depends(get_db),
    _ea: str = Depends(require_ea_api_key),
) -> SimpleStatus:
    command = _get_authorized_callback_command(db, command_id, x_sg_license_key)
    try:
        _event, created = crud.record_management_event(db, command, payload)
    except crud.ManagementEventConflict as exc:
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if not created:
        return SimpleStatus(status="duplicate_ignored")

    note = _NOTIFY_EVENTS.get(payload.event_type)
    if note:
        user = db.get(crud.models.User, command.user_id)
        chat_id = user.telegram_user_id if user else None
        notify_user_and_admins(
            chat_id, f"{note} ({command.symbol} {command.direction}, {command.id})"
        )
    return SimpleStatus(status="ok")
