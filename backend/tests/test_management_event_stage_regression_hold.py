"""Offline regression witness for out-of-order EA management-event stages.

This is a release HOLD test: it records an observed backend state regression
without authorizing EA changes, broker activity, or external acceptance.
"""
from __future__ import annotations

import json

import pytest

from app import crud, models
from app.database import SessionLocal
from .conftest import EA_HEADERS, create_signal, register_user


def test_late_tp1_success_cannot_regress_committed_tp2_stage(client, monkeypatch):
    """A second, differently keyed TP1 receipt must not undo an advanced TP2.

    Stage is part of management-event idempotency identity, so a delayed TP1
    callback with its own stage is not filtered as an exact duplicate.
    Assert that state, ledger result/R and the advancing-audit flag remain
    consistent while the distinct late receipt is retained.
    Synthetic SQLite/PostgreSQL records only; never a broker scenario.
    """
    owner = register_user(client, "990091")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990091"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    polled = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert polled.status_code == 200, polled.text
    command = polled.json()["command"]
    assert command is not None
    command_id = command["command_id"]

    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    # EA emits TP-close receipts before the *separate* stop-loss move result.
    # Customer-facing text must not declare that SL move complete yet.
    from app.routes import commands as command_routes

    stage_notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: stage_notifications.append((args, kwargs)),
    )

    for event_type, stage in (
        ("TP1_CLOSE_SUCCESS", "TP1_DONE"),
        ("TP2_CLOSE_SUCCESS", "TP2_DONE"),
    ):
        response = client.post(
            f"/commands/{command_id}/management_event",
            json={"event_type": event_type, "stage": stage, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ok"

    assert len(stage_notifications) == 2
    for level, (args, _kwargs) in zip(("TP1", "TP2"), stage_notifications):
        message = args[1]
        assert f"Demo EA reports {level} close" in message
        assert f"Broker {level} exit not independently confirmed" in message
        assert "check demo terminal" in message
        assert "Stop-loss change not yet confirmed" in message
        assert "SL moved" not in message

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "PARTIAL_TP2_DONE"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "TP2_HIT"
        assert ledger_row.r_result == pytest.approx(6.5)

    # An accepted stale TP1 receipt must not send a misleading second
    # "TP1 hit / SL moved" notification after TP2 has completed.
    late_notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: late_notifications.append((args, kwargs)),
    )

    late = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_LATE_RETRY",
            "result": "SUCCESS",
        },
        headers=EA_HEADERS,
    )
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "ok"
    assert not late_notifications, "Stale TP1 receipt must not notify after TP2"

    with SessionLocal() as session:
        stored = crud.get_command(session, command_id)
        assert stored is not None
        assert stored.status == "PARTIAL_TP2_DONE"
        events = (
            session.query(models.TradeManagementEvent)
            .filter(models.TradeManagementEvent.command_id == command_id)
            .order_by(models.TradeManagementEvent.id)
            .all()
        )
        assert len(events) == 3, "All three distinct receipts must be persisted"
        assert sorted(event.event_type for event in events) == [
            "TP1_CLOSE_SUCCESS", "TP1_CLOSE_SUCCESS", "TP2_CLOSE_SUCCESS"
        ]
        late_event = next(event for event in events if event.stage == "TP1_LATE_RETRY")
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "TP2_HIT"
        assert ledger_row.r_result == pytest.approx(6.5)
        audit = session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT",
            entity_type="management_event",
            entity_id=late_event.id,
        ).one()
        assert json.loads(audit.payload_json)["state_advanced"] is False

    # The already stored late receipt still obeys normal idempotency.
    repeated = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": "TP1_CLOSE_SUCCESS",
            "stage": "TP1_LATE_RETRY",
            "result": "SUCCESS",
        },
        headers=EA_HEADERS,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "duplicate_ignored"


@pytest.mark.parametrize(
    ("breakeven_result", "tp1_result"),
    [("SUCCESS", "FAILED"), ("FAILED", "SUCCESS")],
)
def test_stop_loss_move_messages_follow_matching_ea_receipts(
    client, monkeypatch, breakeven_result, tp1_result
):
    """A TP close is not SL proof; current-stage SL outcomes notify once.

    Late results from an earlier/closed stage remain audited but do not imply
    new protection. All inputs and notifications are synthetic/offline.
    """
    owner = register_user(client, "990092")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990092"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    pending = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    from app.routes import commands as command_routes

    messages = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda _chat_id, message: messages.append(message),
    )

    def receipt(event_type, stage, result):
        response = client.post(
            f"/commands/{command_id}/management_event",
            json={"event_type": event_type, "stage": stage, "result": result},
            headers=EA_HEADERS,
        )
        assert response.status_code == 200, response.text
        return response.json()["status"]

    assert receipt("TP1_CLOSE_SUCCESS", "TP1_DONE", "SUCCESS") == "ok"
    assert len(messages) == 1
    assert "Demo EA reports TP1 close" in messages[-1]
    assert "Broker TP1 exit not independently confirmed" in messages[-1]
    assert "check demo terminal" in messages[-1]
    assert "not yet confirmed" in messages[-1]
    assert "Demo only" in messages[-1]
    first_type = f"SL_MOVE_BREAKEVEN_{breakeven_result}"
    assert receipt(first_type, "TP1_DONE", breakeven_result) == "ok"
    assert len(messages) == 2
    if breakeven_result == "FAILED":
        assert "FAILED" in messages[-1] and "Protection not confirmed" in messages[-1]
    else:
        assert "Demo EA reported" in messages[-1]
        assert "not independently confirmed" in messages[-1]
        assert "succeeded" not in messages[-1]
    assert receipt(first_type, "TP1_DONE", breakeven_result) == "duplicate_ignored"
    assert len(messages) == 2, "Duplicate management receipt must not notify twice"

    assert receipt("TP2_CLOSE_SUCCESS", "TP2_DONE", "SUCCESS") == "ok"
    assert len(messages) == 3
    assert "Demo EA reports TP2 close" in messages[-1]
    assert "Broker TP2 exit not independently confirmed" in messages[-1]
    assert "check demo terminal" in messages[-1]
    assert "not yet confirmed" in messages[-1]
    assert "Demo only" in messages[-1]
    second_type = f"SL_MOVE_TP1_{tp1_result}"
    assert receipt(second_type, "TP2_DONE", tp1_result) == "ok"
    assert len(messages) == 4
    if tp1_result == "FAILED":
        assert "FAILED" in messages[-1] and "Protection not confirmed" in messages[-1]
    else:
        assert "Demo EA reported" in messages[-1]
        assert "not independently confirmed" in messages[-1]
        assert "succeeded" not in messages[-1]

    opposite_breakeven = "FAILED" if breakeven_result == "SUCCESS" else "SUCCESS"
    assert receipt(
        f"SL_MOVE_BREAKEVEN_{opposite_breakeven}",
        "TP1_LATE_SL_RECEIPT",
        opposite_breakeven,
    ) == "ok"
    assert len(messages) == 4, "Stale TP1 stop-loss receipt must not notify after TP2"

    assert receipt("TP3_CLOSE_SUCCESS", "TP3_DONE", "SUCCESS") == "ok"
    assert len(messages) == 5
    assert "Demo EA reports TP3 child closed" in messages[-1]
    assert "not independently confirmed" in messages[-1]
    assert "check demo terminal" in messages[-1]
    opposite_tp1 = "FAILED" if tp1_result == "SUCCESS" else "SUCCESS"
    assert receipt(
        f"SL_MOVE_TP1_{opposite_tp1}", "TP2_LATE_SL_RECEIPT", opposite_tp1
    ) == "ok"
    assert len(messages) == 5, "Closed command must not notify an old SL move"

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "FULLY_CLOSED"
        events = session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).all()
        assert len(events) == 7, "Distinct late receipts are still persisted for audit"


@pytest.mark.parametrize(
    ("event_type", "result"),
    [
        ("TP1_CLOSE_SUCCESS", "FAILED"),
        ("TP1_CLOSE_SUCCESS", "PENDING"),
        ("TP2_CLOSE_SUCCESS", "FAILED"),
        ("TP3_CLOSE_SUCCESS", "FAILED"),
        # Terminal close/stop callbacks have no suffix but must not turn
        # a failed/pending EA report into a broker-success milestone.
        ("STOP_LOSS_HIT", "FAILED"),
        ("STOP_LOSS_HIT", "PENDING"),
        ("FULLY_CLOSED", "FAILED"),
        ("FULLY_CLOSED", "PENDING"),
        ("SL_MOVE_BREAKEVEN_SUCCESS", "FAILED"),
        ("SL_MOVE_TP1_FAILED", "SUCCESS"),
        # Suffixless state-changing OPENED/FAILED_MANAGEMENT outcomes must
        # agree with explicit results. TP*_REACHED is allowed to be PENDING
        # because reaching a price does not prove a completed management step.
        ("OPENED", "FAILED"),
        ("OPENED", "PENDING"),
        ("FAILED_MANAGEMENT", "SUCCESS"),
        ("FAILED_MANAGEMENT", "PENDING"),
    ],
)
def test_explicitly_contradictory_management_outcomes_are_rejected(
    client, monkeypatch, event_type, result
):
    """Bad EA self-reports must not create a TP milestone, audit or notification.

    This is synthetic evidence only; no actual broker has confirmed a position.
    Missing optional result is still accepted for legacy report compatibility.
    """
    owner = register_user(client, "990093")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990093"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    pending = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    from app.routes import commands as command_routes

    notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )
    rejected = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": event_type,
            "stage": "CONTRADICTORY_RESULT",
            "result": result,
        },
        headers=EA_HEADERS,
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "Management event type and result disagree"
    assert notifications == []

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "EXECUTED_OPEN"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == "EXECUTED_OPEN"
        assert ledger_row.r_result is None
        assert session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).count() == 0
        assert session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT"
        ).count() == 0, "Rejected report must not fabricate a management audit"

    # A malformed first attempt cannot poison the idempotency key of a later
    # corrected callback for the same event/stage.
    corrected_result = (
        "FAILED"
        if event_type.endswith("_FAILED") or event_type == "FAILED_MANAGEMENT"
        else "SUCCESS"
    )
    corrected = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": event_type,
            "stage": "CONTRADICTORY_RESULT",
            "result": corrected_result,
        },
        headers=EA_HEADERS,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "ok"
    if event_type in {"TP3_CLOSE_SUCCESS", "STOP_LOSS_HIT", "FULLY_CLOSED"}:
        assert len(notifications) == 1
        message = notifications[0][0][1]
        assert "Demo EA reports" in message
        assert "not independently confirmed" in message
        assert "check demo terminal" in message
    with SessionLocal() as session:
        assert session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).count() == 1
        assert session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT"
        ).count() == 1, "Corrected report has exactly one management audit"


@pytest.mark.parametrize(
    ("first_event", "first_stage", "late_event", "late_stage", "ledger_status"),
    [
        ("TP3_CLOSE_SUCCESS", "TP3_DONE", "STOP_LOSS_HIT", "FULLY_CLOSED", "TP3_HIT"),
        ("STOP_LOSS_HIT", "FULLY_CLOSED", "TP3_CLOSE_SUCCESS", "TP3_DONE", "STOPPED_OUT"),
    ],
)
def test_late_terminal_milestone_cannot_notify_a_second_exit(
    client, monkeypatch, first_event, first_stage, late_event, late_stage, ledger_status
):
    """Different terminal EA callbacks remain auditable, not a second exit claim.

    The EA emits FULLY_CLOSED after TP3 or stop-out. Do not suppress that
    normal final acknowledgement; only a late *different* milestone is stale.
    Entirely synthetic backend receipts, not broker execution evidence.
    """
    owner = register_user(client, "990094")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990094"},
    )
    assert approval.status_code == 200, approval.text
    command_resp = client.get(
        "/commands/pending",
        params={"user_id": owner["id"]},
        headers=EA_HEADERS,
    )
    assert command_resp.status_code == 200, command_resp.text
    command_id = command_resp.json()["command"]["command_id"]
    opened = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert opened.status_code == 200, opened.text

    from app.routes import commands as command_routes

    messages = []
    monkeypatch.setattr(
        command_routes, "notify_user_and_admins",
        lambda _chat_id, message: messages.append(message),
    )

    def receipt(event_type, stage):
        return client.post(
            f"/commands/{command_id}/management_event",
            json={"event_type": event_type, "stage": stage, "result": "SUCCESS"},
            headers=EA_HEADERS,
        )

    first = receipt(first_event, first_stage)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "ok"
    assert len(messages) == 1
    assert "Demo EA reports" in messages[0]
    assert "not independently confirmed" in messages[0]

    late = receipt(late_event, late_stage)
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "ok"
    assert len(messages) == 1, "Late opposite terminal milestone must not claim a second exit"

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == "FULLY_CLOSED"
        ledger_row = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert ledger_row.result_status == ledger_status
        events = session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id
        ).all()
        assert len(events) == 2, "Keep both distinct EA receipts for operator review"
        late_record = next(e for e in events if e.event_type == late_event)
        audit = session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT",
            entity_type="management_event",
            entity_id=late_record.id,
        ).one()
        assert json.loads(audit.payload_json)["state_advanced"] is False

    # This follows the actual EA's normal TP3/SL event then FULLY_CLOSED flow.
    completed = receipt("FULLY_CLOSED", "FULLY_CLOSED")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "ok"
    assert len(messages) == 2
    assert "trade fully closed" in messages[-1]
    repeated = receipt("FULLY_CLOSED", "FULLY_CLOSED")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "duplicate_ignored"
    assert len(messages) == 2

    # The stage is part of idempotency identity. A delayed closure sent with a
    # new stage is a distinct audit receipt, not a second customer-facing exit.
    late_closure = receipt("FULLY_CLOSED", "LATE_CLOSURE_RECEIPT")
    assert late_closure.status_code == 200, late_closure.text
    assert late_closure.json()["status"] == "ok"
    assert len(messages) == 2, "Different-stage closure must not send duplicate exit"
    with SessionLocal() as session:
        closure_receipts = session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id, event_type="FULLY_CLOSED"
        ).all()
        assert len(closure_receipts) == 2, "Distinct receipts remain in audit history"
        delayed_receipt = next(
            e for e in closure_receipts if e.stage == "LATE_CLOSURE_RECEIPT"
        )
        audit = session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT",
            entity_type="management_event",
            entity_id=delayed_receipt.id,
        ).one()
        assert json.loads(audit.payload_json)["state_advanced"] is False
        assert crud.get_command(session, command_id).status == "FULLY_CLOSED"


def test_postgresql_stale_tp1_callback_cannot_reopen_concurrently_closed_trade(
    client, db, monkeypatch
):
    """Deterministic two-session EA report ordering; synthetic data only.

    An authorised TP1 report reads EXECUTED_OPEN, then pauses before CRUD.
    A second callback reports FULLY_CLOSED and commits in another PostgreSQL
    session. Releasing the delayed TP1 must not reverse command, ledger or
    audit terminal truth. Shared customer-licence locks allow both callbacks;
    a command-state lock/recheck must serialize these separate transactions.
    No real EA, broker, Telegram transport, provider or orders are exercised.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL callback transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, local

    from app.routes import commands as command_routes
    from app.schemas import ManagementEventRequest

    owner = register_user(client, "990095")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990095"},
    )
    assert approved.status_code == 200, approved.text
    pending = client.get(
        "/commands/pending", params={"user_id": owner["id"]}, headers=EA_HEADERS
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    opened = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert opened.status_code == 200, opened.text

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True
    first_lookup_complete = Event()
    release_delayed = Event()
    role = local()
    original_resolver = command_routes._get_authorized_callback_command

    def hold_after_old_command_read(session, command_id, licence_key):
        command = original_resolver(session, command_id, licence_key)
        if getattr(role, "delayed", False):
            assert command.status == "EXECUTED_OPEN"
            first_lookup_complete.set()
            assert release_delayed.wait(timeout=15), (
                "Delayed TP1 callback was never released"
            )
        return command

    monkeypatch.setattr(
        command_routes, "_get_authorized_callback_command",
        hold_after_old_command_read,
    )
    monkeypatch.setattr(
        command_routes, "notify_user_and_admins", lambda *_args, **_kwargs: None
    )

    def report(event_type, stage, *, delayed=False):
        role.delayed = delayed
        with SessionLocal() as session:
            session.connection().exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            response = command_routes.report_management_event(
                command_id,
                ManagementEventRequest(
                    event_type=event_type, stage=stage, result="SUCCESS"
                ),
                x_sg_license_key=owner["license_key"],
                db=session,
                _ea="offline-test",
            )
            return response.status

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            delayed = workers.submit(
                report, "TP1_CLOSE_SUCCESS", "TP1_DONE", delayed=True
            )
            try:
                assert first_lookup_complete.wait(timeout=8), (
                    "TP1 callback never read the old command state"
                )
                terminal = workers.submit(
                    report, "FULLY_CLOSED", "FULLY_CLOSED"
                )
                assert terminal.result(timeout=20) == "ok", (
                    "Independent FULLY_CLOSED report did not commit"
                )
            finally:
                release_delayed.set()
            assert delayed.result(timeout=20) == "ok"

        with SessionLocal() as inspect:
            command = crud.get_command(inspect, command_id)
            assert command is not None
            ledger = inspect.query(models.PerformanceLedger).filter_by(
                signal_id=signal["id"]
            ).one()
            receipts = inspect.query(models.TradeManagementEvent).filter_by(
                command_id=command_id
            ).all()
            assert {event.event_type for event in receipts} == {
                "FULLY_CLOSED", "TP1_CLOSE_SUCCESS"
            }, "Both distinct EA receipts must remain auditable"
            late_tp1 = next(
                event for event in receipts if event.event_type == "TP1_CLOSE_SUCCESS"
            )
            audit = inspect.query(models.AuditLog).filter_by(
                event_type="MANAGEMENT_EVENT",
                entity_type="management_event",
                entity_id=late_tp1.id,
            ).one()
            audit_advanced = json.loads(audit.payload_json)["state_advanced"]
            assert command.status == "FULLY_CLOSED"
            assert ledger.result_status == "CLOSED_UNATTRIBUTED"
            assert ledger.r_result is None
            assert audit_advanced is False
    finally:
        release_delayed.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


def test_postgresql_concurrent_distinct_stage_full_closures_notify_once(
    client, db, monkeypatch
):
    """Two concurrently authorised, differently keyed closes get one notice.

    The second callback must see the first committed FULLY_CLOSED receipt under
    the command-row lock. Keep both distinct audit events but never send two
    apparent trade-exit messages. Synthetic PostgreSQL sessions only; this is
    NOT evidence of an EA fill, broker exit or external acceptance.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL callback transactions")

    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.routes import commands as command_routes
    from app.schemas import ManagementEventRequest

    owner = register_user(client, "990096")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990096"},
    )
    assert approved.status_code == 200, approved.text
    pending = client.get(
        "/commands/pending", params={"user_id": owner["id"]}, headers=EA_HEADERS
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    executed = client.post(
        f"/commands/{command_id}/execution",
        json={"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04},
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True
    start_together = Barrier(2)
    original_resolver = command_routes._get_authorized_callback_command
    messages = []

    def both_read_open_before_command_lock(session, command_id, licence_key):
        command = original_resolver(session, command_id, licence_key)
        assert command.status == "EXECUTED_OPEN"
        start_together.wait(timeout=12)
        return command

    monkeypatch.setattr(
        command_routes, "_get_authorized_callback_command",
        both_read_open_before_command_lock,
    )
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda _chat_id, message: messages.append(message),
    )

    def report(stage):
        with SessionLocal() as session:
            session.connection().exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            return command_routes.report_management_event(
                command_id,
                ManagementEventRequest(
                    event_type="FULLY_CLOSED", stage=stage, result="SUCCESS"
                ),
                x_sg_license_key=owner["license_key"],
                db=session,
                _ea="offline-test",
            ).status

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            reports = [
                workers.submit(report, "PARALLEL_CLOSE_A"),
                workers.submit(report, "PARALLEL_CLOSE_B"),
            ]
            assert [future.result(timeout=25) for future in reports] == ["ok", "ok"]

        assert len(messages) == 1, (
            "Separate concurrent FULLY_CLOSED receipts must not double-notify"
        )
        assert "Demo EA reports trade fully closed" in messages[0]
        assert "not independently confirmed" in messages[0]
        with SessionLocal() as inspect:
            command = crud.get_command(inspect, command_id)
            assert command.status == "FULLY_CLOSED"
            receipts = inspect.query(models.TradeManagementEvent).filter_by(
                command_id=command_id, event_type="FULLY_CLOSED"
            ).all()
            assert {receipt.stage for receipt in receipts} == {
                "PARALLEL_CLOSE_A", "PARALLEL_CLOSE_B"
            }
            advancement = []
            for receipt in receipts:
                audit = inspect.query(models.AuditLog).filter_by(
                    event_type="MANAGEMENT_EVENT",
                    entity_type="management_event",
                    entity_id=receipt.id,
                ).one()
                advancement.append(json.loads(audit.payload_json)["state_advanced"])
            assert sorted(advancement) == [False, True]
            ledger = inspect.query(models.PerformanceLedger).filter_by(
                signal_id=signal["id"]
            ).one()
            assert ledger.result_status == "CLOSED_UNATTRIBUTED"
            assert ledger.r_result is None
    finally:
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode

def test_execution_success_notification_distinguishes_ea_report_from_broker_proof(client, monkeypatch):
    """EA-reported success must not imply independently verified broker filling.

    The success callback and duplicate exercise only synthetic offline backend
    state; neither is MT5 demo-broker acceptance or external confirmation.
    """
    from app.routes import commands as command_routes

    owner = register_user(client, "990097")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990097"},
    )
    assert approved.status_code == 200, approved.text
    pending = client.get(
        "/commands/pending", params={"user_id": owner["id"]}, headers=EA_HEADERS
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]
    notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda _chat_id, message: notifications.append(message),
    )
    payload = {"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04}
    first = client.post(
        f"/commands/{command_id}/execution", json=payload, headers=EA_HEADERS
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "ok"
    assert len(notifications) == 1
    assert "Demo EA reports trade OPENED" in notifications[0]
    assert "Broker fill not independently confirmed" in notifications[0]
    assert "check demo terminal" in notifications[0]
    assert "✅ Demo trade OPENED" not in notifications[0]

    duplicate = client.post(
        f"/commands/{command_id}/execution", json=payload, headers=EA_HEADERS
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "duplicate_ignored"
    assert len(notifications) == 1

@pytest.mark.parametrize(
    ("error_code", "error_message"),
    [
        ("NETWORK_TIMEOUT", "synthetic uncertain broker response"),
        (
            "INJECTED\nBROKER_CONFIRMED_" + "X" * 5000,
            "synthetic-secret-not-for-telegram\nBROKER CONFIRMED\n" + "Y" * 5000,
        ),
    ],
)
def test_execution_failure_notification_distinguishes_ea_report_from_broker_proof(
    client, monkeypatch, error_code, error_message
):
    """A FAILED EA callback does not prove that no broker position was opened.

    Synthetic offline notification evidence only; this does not reconcile
    ambiguous broker outcomes or constitute MT5 demo-broker acceptance.
    """
    from app.routes import commands as command_routes

    owner = register_user(client, "990098")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990098"},
    )
    assert approved.status_code == 200, approved.text
    pending = client.get(
        "/commands/pending", params={"user_id": owner["id"]}, headers=EA_HEADERS
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]

    notifications = []
    monkeypatch.setattr(
        command_routes,
        "notify_user_and_admins",
        lambda _chat_id, message: notifications.append(message),
    )
    payload = {
        "status": "FAILED",
        "error_code": error_code,
        "error_message": error_message,
    }
    first = client.post(
        f"/commands/{command_id}/execution", json=payload, headers=EA_HEADERS
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "ok"
    assert len(notifications) == 1
    assert "Demo EA reports execution FAILED" in notifications[0]
    assert "Broker outcome not independently confirmed" in notifications[0]
    assert "check demo terminal" in notifications[0]
    assert "EA error details are not included in messages" in notifications[0]
    assert "NETWORK_TIMEOUT" not in notifications[0]
    assert error_code not in notifications[0]
    assert error_message not in notifications[0]
    assert "BROKER CONFIRMED" not in notifications[0]
    assert "\n" not in notifications[0]
    assert len(notifications[0]) < 4096
    assert "⚠️ Demo trade FAILED" not in notifications[0]
    with SessionLocal() as session:
        stored = session.query(models.Execution).filter_by(command_id=command_id).one()
        assert stored.error_code == error_code
        assert stored.error_message == error_message

    duplicate = client.post(
        f"/commands/{command_id}/execution", json=payload, headers=EA_HEADERS
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "duplicate_ignored"
    assert len(notifications) == 1


@pytest.mark.parametrize("terminal_status", ["FAILED", "EXPIRED"])
def test_late_full_closure_after_nonclosure_terminal_is_audit_only(
    client, monkeypatch, terminal_status
):
    """A delayed EA FULLY_CLOSED must not claim an exit after failure/expiry.

    CRUD must retain the distinct self-report and its nonadvancing audit, but
    neither a failed execution nor an expired command proves a broker closure.
    This uses synthetic backend records only, not broker-demo acceptance.
    """
    from app.routes import commands as command_routes

    owner = register_user(client, "990100")
    signal = create_signal(client, "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990100"},
    )
    assert approval.status_code == 200, approval.text
    pending = client.get(
        "/commands/pending", params={"user_id": owner["id"]}, headers=EA_HEADERS
    )
    assert pending.status_code == 200, pending.text
    command_id = pending.json()["command"]["command_id"]

    execution_payload = (
        {"status": "FAILED", "error_code": "EA_REJECTED"}
        if terminal_status == "FAILED"
        else {"status": "SUCCESS", "executed_price": 2345.0, "lot_size": 0.04}
    )
    executed = client.post(
        f"/commands/{command_id}/execution",
        json=execution_payload,
        headers=EA_HEADERS,
    )
    assert executed.status_code == 200, executed.text

    with SessionLocal() as session:
        command = crud.get_command(session, command_id)
        if terminal_status == "EXPIRED":
            # Deterministic stale-callback simulation, not a broker scenario.
            command.status = "EXPIRED"
            session.commit()
        assert command.status == terminal_status
        ledger = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        prior_ledger = (ledger.result_status, ledger.r_result)

    notifications = []
    monkeypatch.setattr(
        command_routes, "notify_user_and_admins",
        lambda _chat_id, message: notifications.append(message),
    )
    late = client.post(
        f"/commands/{command_id}/management_event",
        json={
            "event_type": "FULLY_CLOSED",
            "stage": "LATE_AFTER_NONCLOSURE_TERMINAL",
            "result": "SUCCESS",
        },
        headers=EA_HEADERS,
    )
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "ok"
    assert notifications == [], "Late receipt is not verified broker closure"

    with SessionLocal() as session:
        assert crud.get_command(session, command_id).status == terminal_status
        ledger = session.query(models.PerformanceLedger).filter_by(
            signal_id=signal["id"]
        ).one()
        assert (ledger.result_status, ledger.r_result) == prior_ledger
        receipt = session.query(models.TradeManagementEvent).filter_by(
            command_id=command_id, event_type="FULLY_CLOSED"
        ).one()
        audit = session.query(models.AuditLog).filter_by(
            event_type="MANAGEMENT_EVENT",
            entity_type="management_event",
            entity_id=receipt.id,
        ).one()
        assert json.loads(audit.payload_json)["state_advanced"] is False
