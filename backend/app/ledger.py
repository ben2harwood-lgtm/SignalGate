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
                "Executed (demo). Entry price not reported; realised R unverified."
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

    # TP/SL milestones cannot prove a realised return for the whole position.
    # Event reports lack verified aggregate fill/exit volumes and may follow
    # earlier partial closes or stop moves. Do not invent scalar whole-trade R.
    if event.event_type in {
        "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS",
        "STOP_LOSS_HIT", "FULLY_CLOSED", "FAILED_MANAGEMENT",
        "SL_MOVE_BREAKEVEN_SUCCESS",
    }:
        led.r_result = None
        if event.event_type in {
            "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS", "TP3_CLOSE_SUCCESS",
        }:
            led.final_notes = (
                "Take-profit stage reported (demo). Whole-trade realised R "
                "unverified without broker-confirmed fill and close volumes."
            )
        elif event.event_type == "STOP_LOSS_HIT":
            led.final_notes = (
                "Stop-loss exit reported (demo). Whole-trade realised R "
                "unverified; earlier partial exits and stop moves may apply."
            )
        elif event.event_type == "FAILED_MANAGEMENT":
            led.final_notes = (
                "Management failure reported (demo); realised outcome unverified."
            )

    # Breakeven detection: if SL was moved to entry/open and price hit it.
    if event.event_type == "SL_MOVE_BREAKEVEN_SUCCESS":
        led.final_notes = "Stop moved to breakeven after TP1."

    if event.event_type == "FULLY_CLOSED":
        if led.result_status not in {
            "STOPPED_OUT", "FAILED", "TP1_HIT", "TP2_HIT", "TP3_HIT",
        }:
            led.result_status = "CLOSED_UNATTRIBUTED"
            led.final_notes = (
                "Trade reported fully closed without TP/SL attribution; "
                "manual reconciliation required."
            )
        else:
            led.final_notes = (
                "Demo position reported fully closed after a TP/SL stage; "
                "whole-trade realised R unverified pending broker exit evidence."
            )
        led.r_result = None

    led.updated_at = utcnow()
    db.flush()
