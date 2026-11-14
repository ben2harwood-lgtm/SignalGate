"""Offline lock-order control for two correctly authorised demo EA callbacks.

This is a synthetic PostgreSQL concurrency test, not MT5/broker evidence.
It protects the existing Command->audit order from a future late account-
provenance fence that would acquire Command AFTER the audit advisory lock.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text

from app import crud, models
from app.database import SessionLocal
from app.routes import commands as command_routes
from app.schemas import ExecutionRequest, ManagementEventRequest

from .conftest import EA_HEADERS, register_user
from .test_provider_export import _headers, _provider


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def test_postgresql_duplicate_execution_and_tp_close_preserve_lock_order(
    client, db, monkeypatch
):
    """A held audit advisory lock must not deadlock with a Command write lock.

    A duplicate execution retry acquires the audit-chain advisory lock and
    deliberately pauses. A concurrent state-changing TP1 close locks Command
    FOR UPDATE, then waits for the audit-chain lock. The duplicate must be
    able to finish while TP1 holds its Command lock; both receipts must commit,
    and the chain must verify. A future post-audit Command FOR SHARE would
    create the opposite lock order and cause this test to fail, not XFAIL.

    No live EA, broker, order, trading account connection or customer is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    provider, feed, provider_key = _provider(db, "offline-callback-lock-order")
    db.commit()
    owner = register_user(
        client, "990383", "synthetic_lock_order_owner", "Synthetic Owner"
    )
    _, account = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    assert account.user_id == owner["id"]
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, provider_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": owner["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"
    command_id = approved.json()["command_id"]
    db.rollback()

    claimed = client.get(
        "/commands/pending", headers=EA_HEADERS,
        params={"user_id": owner["id"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id

    # Seed an already executed *synthetic* command. No order is transmitted.
    execution_payload = ExecutionRequest(
        status="SUCCESS",
        broker_ticket="OFFLINE-LOCK-ORDER-NO-BROKER",
        executed_symbol="XAUUSD",
        executed_direction="BUY",
        executed_price=2345.0,
        lot_size=0.1,
    )
    with monkeypatch.context() as patch:
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_kw: None)
        initial = command_routes.report_execution(
            command_id,
            execution_payload,
            x_sg_license_key="",
            db=db,
            _ea="offline-test",
        )
    assert initial.status == "ok"
    db.rollback()

    roles = local()
    duplicate_has_audit_lock = Event()
    release_duplicate = Event()
    tp_entered_crud_with_command_lock = Event()
    tp_pid: dict[str, int] = {}
    original_lock = crud._lock_audit_chain
    original_management_record = crud.record_management_event

    def pause_duplicate_after_real_advisory_lock(session):
        original_lock(session)
        if getattr(roles, "name", None) == "duplicate":
            duplicate_has_audit_lock.set()
            assert release_duplicate.wait(timeout=12), (
                "Duplicate callback was not released from audit-lock barrier"
            )

    def record_tp_after_command_lock(session, command, payload):
        # report_management_event calls refresh(..., with_for_update=True)
        # before it reaches this function for TP1_CLOSE_SUCCESS.
        tp_entered_crud_with_command_lock.set()
        return original_management_record(session, command, payload)

    def duplicate_retry():
        roles.name = "duplicate"
        with SessionLocal() as session:
            session.connection().exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            return command_routes.report_execution(
                command_id,
                execution_payload,
                x_sg_license_key=owner["license_key"],
                db=session,
                _ea="offline-test",
            ).status

    def tp_close():
        roles.name = "tp"
        with SessionLocal() as session:
            session.connection().exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            tp_pid["value"] = session.connection().exec_driver_sql(
                "SELECT pg_backend_pid()"
            ).scalar_one()
            return command_routes.report_management_event(
                command_id,
                ManagementEventRequest(
                    event_type="TP1_CLOSE_SUCCESS",
                    stage="TP1_CLOSED",
                    result="SUCCESS",
                ),
                x_sg_license_key=owner["license_key"],
                db=session,
                _ea="offline-test",
            ).status

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(crud, "_lock_audit_chain", pause_duplicate_after_real_advisory_lock)
        patch.setattr(crud, "record_management_event", record_tp_after_command_lock)
        patch.setattr(command_routes, "notify_user_and_admins", lambda *_a, **_kw: None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicate = pool.submit(duplicate_retry)
            try:
                assert duplicate_has_audit_lock.wait(timeout=8), (
                    "Duplicate never acquired the actual audit advisory lock"
                )
                management = pool.submit(tp_close)
                assert tp_entered_crud_with_command_lock.wait(timeout=8), (
                    "State-changing TP never acquired Command FOR UPDATE"
                )

                # Prove specifically an advisory-lock wait, not merely any
                # PostgreSQL Lock event (e.g. a Command row/transaction lock).
                tp_waiting_on_audit_lock = False
                with SessionLocal() as observer:
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        wait_event = observer.execute(
                            text(
                                "SELECT wait_event FROM pg_stat_activity "
                                "WHERE pid = :pid AND wait_event_type = 'Lock'"
                            ),
                            {"pid": tp_pid["value"]},
                        ).scalar_one_or_none()
                        if wait_event == "advisory":
                            tp_waiting_on_audit_lock = True
                            break
                        sleep(0.05)
                assert tp_waiting_on_audit_lock, (
                    "TP did not enter the expected PostgreSQL advisory-lock wait"
                )
                assert not management.done(), (
                    "State-changing TP escaped the held audit-lock barrier"
                )
            finally:
                release_duplicate.set()
            duplicate_status = duplicate.result(timeout=20)
            management_status = management.result(timeout=20)

    assert duplicate_status == "duplicate_ignored"
    assert management_status == "ok"
    with SessionLocal() as session:
        command = session.get(models.Command, command_id)
        assert command is not None and command.status == "PARTIAL_TP1_DONE"
        assert session.scalar(
            select(models.Execution.id).where(models.Execution.command_id == command_id)
        ) is not None
        assert session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).count() == 1
        assert session.query(models.TradeManagementEvent).filter(
            models.TradeManagementEvent.command_id == command_id,
            models.TradeManagementEvent.event_type == "TP1_CLOSE_SUCCESS",
        ).count() == 1
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "DUPLICATE_EXECUTION_REPORT_IGNORED",
            models.AuditLog.entity_id == command_id,
        ).count() == 1
        verification = crud.verify_audit_chain(session)
        assert verification["valid"], verification
