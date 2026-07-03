"""Performance ledger.

Tracks the full lifecycle of each signal for honest forward-testing records.
We never fabricate profitability. R values are approximate and clearly marked
provisional when entry price is unknown.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .models import utcnow


def _get_ledger_for_signal(
    db: Session, signal_id: str
) -> Optional[models.PerformanceLedger]:
    return db.scalar(
        select(models.PerformanceLedger).where(
            models.PerformanceLedger.signal_id == signal_id
        )
    )


def _next_ledger_id(db: Session) -> str:
    from .crud import _next_id

    return _next_id(db, models.PerformanceLedger)


def create_ledger_for_signal(
    db: Session, signal: models.Signal
) -> models.PerformanceLedger:
    """Create a ledger row for every signal at creation time."""
    if signal.parser_status == "VALID":
        result_status = "PENDING"
    else:
        result_status = "REJECTED"

    led = models.PerformanceLedger(
        id=_next_ledger_id(db),
        signal_id=signal.id,
        symbol=signal.symbol,
        direction=signal.direction,
        entry_price=signal.entry_price,
        initial_stop_loss=signal.initial_stop_loss,
        tp1=signal.tp1,
        tp2=signal.tp2,
        tp3=signal.tp3,
        result_status=result_status,
        final_notes="Signal recorded." if signal.parser_status == "VALID"
        else f"Parser rejected: {signal.parser_error}",
    )
    db.add(led)
    db.flush()
    return led


def on_rejected(db: Session, signal: models.Signal) -> None:
    led = _get_ledger_for_signal(db, signal.id)
    if led is None:
        return
    led.result_status = "REJECTED"
    led.final_notes = "User rejected signal. No command created."
    led.updated_at = utcnow()
    db.flush()


def on_command_created(
    db: Session, signal: models.Signal, command: models.Command
) -> None:
    led = _get_ledger_for_signal(db, signal.id)
    if led is None:
        return
    led.command_id = command.id
    led.result_status = "APPROVED_NOT_EXECUTED"
    # signal -> card/command delay in seconds.
    delta = (command.created_at - signal.created_at).total_seconds()
    led.signal_to_card_delay = delta
    led.final_notes = "Command created, awaiting EA execution."
    led.updated_at = utcnow()
    db.flush()


def _approx_r(direction: str, entry: float, sl: float, target: float) -> Optional[float]:
    """Approximate R multiple for a target price.

    BUY:  risk = entry - sl ; reward = target - entry
    SELL: risk = sl - entry ; reward = entry - target
    """
    if entry is None or sl is None or target is None:
        return None
    if direction == "BUY":
        risk = entry - sl
        reward = target - entry
    else:
        risk = sl - entry
        reward = entry - target
    if risk <= 0:
        return None
    return round(reward / risk, 3)


def on_execution(
    db: Session, command: models.Command, execution: models.Execution
) -> None:
    led = _get_ledger_for_signal(db, command.signal_id)
    if led is None:
        return

    if execution.status == "SUCCESS":
        led.result_status = "EXECUTED_OPEN"
        led.command_id = command.id
        led.entry_price = execution.executed_price or command.entry_price
        led.slippage = execution.slippage
        led.spread_at_execution = execution.spread_at_execution
        # approval -> execution delay.
        if command.sent_to_ea_at:
            led.approval_to_execution_delay = (
                execution.created_at - command.created_at
            ).total_seconds()
        if execution.executed_price is None:
            led.final_notes = (
                "Executed (demo). Entry price not reported; R values provisional."
            )
        else:
            led.final_notes = "Executed (demo). Position opened."
    else:
        led.result_status = "FAILED"
        led.final_notes = (
            f"Execution failed: {execution.error_code} {execution.error_message}"
        )
    led.updated_at = utcnow()
    db.flush()


# Management event_type -> ledger result_status transitions.
_EVENT_TO_LEDGER_STATUS = {
    "TP1_CLOSE_SUCCESS": "TP1_HIT",
    "TP2_CLOSE_SUCCESS": "TP2_HIT",
    "TP3_CLOSE_SUCCESS": "TP3_HIT",
    "STOP_LOSS_HIT": "STOPPED_OUT",
    "FAILED_MANAGEMENT": "FAILED",
}


def on_management_event(
    db: Session, command: models.Command, event: models.TradeManagementEvent
) -> None:
    led = _get_ledger_for_signal(db, command.signal_id)
    if led is None:
        return

    new_status = _EVENT_TO_LEDGER_STATUS.get(event.event_type)
    if new_status:
        led.result_status = new_status

    # Update approximate R based on the highest TP reached.
    entry = led.entry_price if led.entry_price is not None else command.entry_price
    if entry is not None:
        target = None
        if event.event_type == "TP1_CLOSE_SUCCESS":
            target = command.tp1
        elif event.event_type == "TP2_CLOSE_SUCCESS":
            target = command.tp2
        elif event.event_type == "TP3_CLOSE_SUCCESS":
            target = command.tp3
        elif event.event_type == "STOP_LOSS_HIT":
            # Stopped out -> approx -1R (or breakeven if SL moved up).
            led.r_result = -1.0
        if target is not None:
            r = _approx_r(command.direction, entry, command.initial_stop_loss, target)
            if r is not None:
                led.r_result = r

    # Breakeven detection: if SL was moved to entry/open and price hit it.
    if event.event_type == "SL_MOVE_BREAKEVEN_SUCCESS":
        led.final_notes = "Stop moved to breakeven after TP1."

    # A bare FULLY_CLOSED with no prior TP/SL event must NOT be booked as a
    # full TP3 winner -- that silently flatters the record. Leave the last
    # known result_status and note that the close could not be attributed.
    if event.event_type == "FULLY_CLOSED" and led.result_status not in {
        "STOPPED_OUT",
        "FAILED",
        "TP1_HIT",
        "TP2_HIT",
        "TP3_HIT",
        "BREAKEVEN",
    }:
        led.final_notes = (
            (led.final_notes + " " if led.final_notes else "")
            + "Closed with no TP/SL event reported; outcome unattributed."
        )

    led.updated_at = utcnow()
    db.flush()
