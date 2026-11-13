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

    # Keep the Command lookup nonlocking: a row lock here would prevent
    # legitimate concurrent duplicate execution callbacks from reaching the
    # uniqueness/SAVEPOINT retry path. The independent Signal and Approval
    # provenance below is SHARE-locked through the caller's commit.
    command = db.scalar(
        select(Command)
        .where(Command.id == command_id, Command.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    if command is None:
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )

    # A current licence plus mutable Command.user_id does NOT establish the
    # subscriber who originally approved and received this command. Check the
    # independent origin and approval links, without requiring the approval to
    # remain active AFTER delivery: late broker-truth receipts must survive
    # subsequent revocations/pauses. SHARE locks hold these links to commit.
    origin_query = select(
        crud.models.Signal.provider_id, crud.models.Signal.feed_id
    ).where(crud.models.Signal.id == command.signal_id)
    approval_query = select(crud.models.Approval).where(
        crud.models.Approval.id == command.approval_id
    )
    if db.get_bind().dialect.name == "postgresql":
        origin_query = origin_query.with_for_update(read=True)
        approval_query = approval_query.with_for_update(read=True)
    origin = db.execute(origin_query).one_or_none()
    approval = db.scalar(
        approval_query.execution_options(populate_existing=True)
    )
    if (
        origin is None
        or (origin.provider_id, origin.feed_id) != (
            command.provider_id, command.feed_id
        )
        or approval is None
        or approval.signal_id != command.signal_id
        or approval.user_id != user.id
    ):
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )

    # Account ownership is another independent tenant link. A delivered
    # command's mutable account_id must still identify this subscriber's
    # account under the ORIGINAL provider; a valid licence and YES alone do
    # not authorize a receipt attributed to somebody else's account.
    # Preserve late broker truth after an account is paused/deactivated:
    # historical callback authorization does not require ACTIVE status.
    account_query = select(crud.models.TradingAccount.id).where(
        crud.models.TradingAccount.id == command.account_id,
        crud.models.TradingAccount.user_id == user.id,
        crud.models.TradingAccount.provider_id == command.provider_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        account_query = account_query.with_for_update(read=True)
    if db.scalar(account_query) is None:
        raise HTTPException(
            status_code=403, detail="Command does not belong to this EA licence"
        )

    # A hosted EA licence cannot turn an undelivered command into a broker
    # receipt. In particular, local-demo PENDING rows can survive a synthetic
    # migration to hosted mode without ever passing the hosted claim guard.
    # This excludes only unclaimed PENDING commands: already-delivered and
    # terminal callbacks remain available for idempotency and broker truth.
    if command.status == "PENDING" and command.sent_to_ea_at is None:
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
    if settings.require_license:
        # The initial licence lookup can become stale before claim. Serialize
        # hosted delivery with licence rotation/deactivation, and recheck the
        # credential after any PostgreSQL row-lock wait. Keep the shared customer
        # lock until the command claim and its audit commit together.
        current_customer = select(crud.models.User).where(
            crud.models.User.id == user.id,
            crud.models.User.status == "ACTIVE",
            crud.models.User.license_key_hash == crud.hash_license_key(
                presented_license or ""
            ),
        )
        if db.get_bind().dialect.name == "postgresql":
            current_customer = current_customer.with_for_update(read=True)
        if db.scalar(current_customer.execution_options(populate_existing=True)) is None:
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
    if settings.require_license and db.get_bind().dialect.name == "postgresql":
        # The initial Command lookup was deliberately nonlocking for concurrent
        # execution/SAVEPOINT retries. But an acknowledgement is audit-only:
        # SHARE-lock its own Command row through COMMIT, and recheck every
        # original tenant link after waiting for a concurrent account relabel.
        # Do not prelock execution/reconciliation/management callback paths.
        unchanged_id = db.scalar(
            select(Command.id).where(
                Command.id == command.id,
                Command.user_id == command.user_id,
                Command.provider_id == command.provider_id,
                Command.feed_id == command.feed_id,
                Command.signal_id == command.signal_id,
                Command.approval_id == command.approval_id,
                Command.account_id == command.account_id,
            ).with_for_update(read=True)
        )
        if unchanged_id is None:
            raise HTTPException(
                status_code=403, detail="Command does not belong to this EA licence"
            )
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
            f"ℹ️ Demo EA reports trade OPENED for {command.symbol} {command.direction} "
            f"(command {command.id}). Broker fill not independently confirmed; "
            "check demo terminal. Demo only.",
        )
    else:
        notify_user_and_admins(
            chat_id,
            f"⚠️ Demo EA reports execution FAILED for {command.symbol} {command.direction} "
            f"(command {command.id}). EA error details are not included in messages; "
            "Broker outcome not independently confirmed; check demo terminal. Demo only.",
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
    # A TP-close callback precedes the independent SL_MOVE_* callback in EA.
    # EA MoveRemainingSL may return true without a matching position; even a
    # SUCCESS event is an EA self-report, not independent broker protection proof.
    # Do not imply the remaining stop-loss is already protected.
    # Terminal TP3/stop/close messages are EA self-reports until separately
    # reconciled against broker-demo receipts; never assert a verified exit.
    "TP1_CLOSE_SUCCESS": "🎯 Demo EA reports TP1 close. Broker TP1 exit not independently confirmed; check demo terminal. Stop-loss change not yet confirmed. Demo only.",
    "TP2_CLOSE_SUCCESS": "🎯 Demo EA reports TP2 close. Broker TP2 exit not independently confirmed; check demo terminal. Stop-loss change not yet confirmed. Demo only.",
    "SL_MOVE_BREAKEVEN_SUCCESS": "ℹ️ Demo EA reported breakeven SL modification: SUCCESS. Actual protection not independently confirmed; check demo position.",
    "SL_MOVE_BREAKEVEN_FAILED": "⚠️ Demo EA reports breakeven stop-loss move FAILED. Protection not confirmed; check demo terminal.",
    "SL_MOVE_TP1_SUCCESS": "ℹ️ Demo EA reported TP1 SL modification: SUCCESS. Actual protection not independently confirmed; check demo position.",
    "SL_MOVE_TP1_FAILED": "⚠️ Demo EA reports TP1 stop-loss move FAILED. Protection not confirmed; check demo terminal.",
    "TP3_CLOSE_SUCCESS": "🎯 Demo EA reports TP3 child closed. Broker exit not independently confirmed; check demo terminal.",
    "FULLY_CLOSED": "🏁 Demo EA reports trade fully closed. Broker closure not independently confirmed; check demo terminal.",
    "STOP_LOSS_HIT": "🛑 Demo EA reports stop-loss exit. Broker exit not independently confirmed; check demo terminal.",
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
    # A different callback can close the command after its first authorised
    # SELECT, leaving this Session's Command object stale under PostgreSQL
    # READ COMMITTED. Serialize state-changing management receipts on the
    # command row and refresh the ORM snapshot BEFORE the terminal/stage guard.
    # The shared customer-licence lock protects revocation, not command state.
    # TP*_REACHED is only a price observation: keep its existing independent
    # duplicate-key race/retry coverage without taking a command write lock.
    if (
        db.get_bind().dialect.name == "postgresql"
        and payload.event_type not in {"TP1_REACHED", "TP2_REACHED", "TP3_REACHED"}
    ):
        db.refresh(command, with_for_update=True)
    # Capture pre-report terminal truth: CRUD records distinct late receipts
    # without re-opening a finished command, but post-commit status alone
    # cannot distinguish a fresh exit from a contradictory late exit.
    terminal_before_receipt = command.status in {"FULLY_CLOSED", "FAILED", "EXPIRED"}
    # A distinct stage may create a new FULLY_CLOSED audit receipt even after
    # the EA has already reported closure. Keep that audit, but send the final
    # closure notice at most once per command. This must be read before insert;
    # the PostgreSQL command-row lock above serializes concurrent callbacks.
    prior_full_closure = (
        payload.event_type == "FULLY_CLOSED"
        and db.scalar(
            select(crud.models.TradeManagementEvent.id).where(
                crud.models.TradeManagementEvent.command_id == command.id,
                crud.models.TradeManagementEvent.event_type == "FULLY_CLOSED",
            ).limit(1)
        ) is not None
    )
    # An explicit EA result contradicting the event name is not execution
    # evidence. Refuse it before CRUD can advance command/ledger state or
    # create a misleading success notification. None remains compatible with
    # older report clients; explicit contradictions are never accepted.
    expected_result = None
    # Suffixless OPENED/terminal callbacks imply a completed outcome.
    # TP*_REACHED is only a price observation: management may still be PENDING,
    # including in PostgreSQL licence-revocation/idempotency regressions.
    if payload.event_type.endswith("_SUCCESS") or payload.event_type in {
        "STOP_LOSS_HIT", "FULLY_CLOSED", "OPENED",
    }:
        expected_result = "SUCCESS"
    elif payload.event_type.endswith("_FAILED") or payload.event_type == "FAILED_MANAGEMENT":
        expected_result = "FAILED"
    if expected_result and payload.result not in (None, expected_result):
        db.rollback()
        raise HTTPException(
            status_code=422, detail="Management event type and result disagree"
        )
    try:
        _event, created = crud.record_management_event(db, command, payload)
    except crud.ManagementEventConflict as exc:
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if not created:
        return SimpleStatus(status="duplicate_ignored")

    note = _NOTIFY_EVENTS.get(payload.event_type)
    # A distinct late TP receipt is still audited, but must not tell the
    # customer an earlier milestone just happened after a later stage or close.
    # This is notification-only: command/ledger execution rules are unchanged.
    if (
        # The EA legitimately follows TP3/STOP_LOSS_HIT with FULLY_CLOSED.
        # Retain that final notice, but never announce a new competing exit
        # from a distinct late TP/SL/failure receipt after terminal state.
        # Allow the EA's normal follow-on FULLY_CLOSED after a TP3/stop-out
        # terminal milestone, but do not announce a broker exit after a
        # FAILED/EXPIRED command: the late receipt is audit-only in CRUD.
        (terminal_before_receipt and (
            payload.event_type != "FULLY_CLOSED"
            or command.status != "FULLY_CLOSED"
        ))
        or prior_full_closure
        or (payload.event_type == "TP1_CLOSE_SUCCESS" and command.status in {
            "PARTIAL_TP2_DONE", "FULLY_CLOSED"
        })
        or (payload.event_type == "TP2_CLOSE_SUCCESS" and command.status == "FULLY_CLOSED")
        # A delayed SL receipt from an earlier/closed stage must not imply
        # that current protection has changed. Keep its audit receipt.
        or (payload.event_type in {"SL_MOVE_BREAKEVEN_SUCCESS", "SL_MOVE_BREAKEVEN_FAILED"}
            and command.status != "PARTIAL_TP1_DONE")
        or (payload.event_type in {"SL_MOVE_TP1_SUCCESS", "SL_MOVE_TP1_FAILED"}
            and command.status != "PARTIAL_TP2_DONE")
        # Never announce success if the EA event type and result disagree.
        or (payload.event_type.startswith("SL_MOVE_")
            and payload.result != ("SUCCESS" if payload.event_type.endswith("_SUCCESS") else "FAILED"))
    ):
        note = None
    if note:
        user = db.get(crud.models.User, command.user_id)
        chat_id = user.telegram_user_id if user else None
        notify_user_and_admins(
            chat_id, f"{note} ({command.symbol} {command.direction}, {command.id})"
        )
    return SimpleStatus(status="ok")
