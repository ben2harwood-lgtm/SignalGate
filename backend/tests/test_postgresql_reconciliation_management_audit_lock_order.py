"""Broker-free PostgreSQL witness for audit-vs-Command lock ordering.

Prevents a future account-provenance fence from adding a Command lock *after*
reconciliation holds the audit advisory lock. No EA, broker or actual orders.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from time import monotonic, sleep

import pytest
from sqlalchemy import text

from app import crud, models
from app.database import SessionLocal
from app.routes import commands as routes
from app.schemas import BrokerPositionReconcileRequest, ManagementEventRequest
from .conftest import EA_HEADERS, register_user
from .test_commands import _hosted_provider_signal_for


def test_postgresql_reconciliation_audit_vs_management_command_lock(
    client, db, monkeypatch,
):
    """A: audit lock -> re-attest, B: Command FOR UPDATE -> audit wait.

    Require a *real* pg_stat_activity advisory wait while B holds its Command
    lock. Both operations must commit without SQLSTATE 40P01 and without
    altering the original synthetic fill. Do not XFAIL a deadlock.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL sessions")
    owner = register_user(client, "990373")
    signal = _hosted_provider_signal_for(client, "990373")
    approval = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990373"},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["result"] == "APPROVED"
    ticket = "990373000001"

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(routes.settings, "require_license", True)
        patch.setattr(routes, "notify_user_and_admins", lambda *_a, **_kw: None)
        headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        pending = client.get("/commands/pending", headers=headers)
        assert pending.status_code == 200, pending.text
        command_id = pending.json()["command"]["command_id"]
        seeded = client.post(
            f"/commands/{command_id}/execution",
            headers=headers,
            json={
                "status": "SUCCESS", "broker_ticket": ticket,
                "executed_symbol": "XAUUSD", "executed_direction": "BUY",
                "executed_price": 2345.0, "lot_size": 0.1,
            },
        )
        assert seeded.status_code == 200, seeded.text
        assert seeded.json()["status"] == "ok"

        # Pin the command's complete origin before the two real PG sessions race.
        # A successful callback must not silently transfer the approved trade.
        with SessionLocal() as origin_session:
            original = origin_session.get(models.Command, command_id)
            assert original is not None
            original_origin = (
                original.account_id, original.provider_id, original.feed_id,
                original.user_id, original.signal_id, original.approval_id,
            )
            assert original.account_id is not None

        roles = local()
        audit_locked, release_audit, manager_at_audit = (
            Event(), Event(), Event()
        )
        pids = {}
        original_lock = crud._lock_audit_chain

        def staged_lock(session):
            role = getattr(roles, "name", None)
            if role == "management":
                # Management already ran db.refresh(command, FOR UPDATE).
                manager_at_audit.set()
            original_lock(session)
            if role == "reconciliation":
                audit_locked.set()
                assert release_audit.wait(timeout=15), (
                    "Reconciliation audit barrier timed out"
                )

        patch.setattr(crud, "_lock_audit_chain", staged_lock)

        def reconcile():
            roles.name = "reconciliation"
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                pids["reconciliation"] = session.connection().exec_driver_sql(
                    "SELECT pg_backend_pid()"
                ).scalar_one()
                return routes.reconcile_open_position(
                    command_id, BrokerPositionReconcileRequest(
                        broker_tickets=[ticket], executed_symbol="XAUUSD",
                        executed_direction="BUY", executed_price=2345.0,
                        lot_size=0.1,
                    ), x_sg_license_key=owner["license_key"],
                    db=session, _ea="offline-test",
                ).status

        def manage():
            roles.name = "management"
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                pids["management"] = session.connection().exec_driver_sql(
                    "SELECT pg_backend_pid()"
                ).scalar_one()
                return routes.report_management_event(
                    command_id, ManagementEventRequest(
                        event_type="TP1_CLOSE_SUCCESS",
                        stage="TP1_CLOSED", result="SUCCESS",
                    ), x_sg_license_key=owner["license_key"],
                    db=session, _ea="offline-test",
                ).status

        with ThreadPoolExecutor(max_workers=2) as pool:
            reconciliation = pool.submit(reconcile)
            try:
                assert audit_locked.wait(timeout=8), (
                    "Reconciliation did not acquire the PG advisory lock"
                )
                management = pool.submit(manage)
                assert manager_at_audit.wait(timeout=8), (
                    "Management did not reach audit after Command FOR UPDATE"
                )
                observed_wait = False
                with SessionLocal() as observer:
                    deadline = monotonic() + 8
                    while monotonic() < deadline:
                        if "management" in pids and "reconciliation" in pids:
                            wait = observer.execute(text(
                                "SELECT wait_event, pg_blocking_pids(pid) "
                                "FROM pg_stat_activity WHERE pid=:pid"
                            ), {"pid": pids["management"]}).first()
                            if (wait and wait[0] == "advisory"
                                and pids["reconciliation"] in wait[1]):
                                observed_wait = True
                                break
                        sleep(0.05)
                assert observed_wait, (
                    "No PostgreSQL advisory-lock wait; a scheduled thread "
                    "is not concurrency proof"
                )
            finally:
                release_audit.set()
            # A future audit->Command fence must raise an actual PG deadlock
            # error here, not turn the defect into a passing XFAIL.
            assert reconciliation.result(timeout=22) == "matched"
            assert management.result(timeout=22) == "ok"

    with SessionLocal() as session:
        execution = session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).one()
        assert execution.user_id == owner["id"]
        assert execution.status == "SUCCESS"
        assert execution.broker_ticket == ticket
        assert execution.executed_price == 2345.0
        assert execution.lot_size == 0.1
        command = session.get(models.Command, command_id)
        assert command is not None and command.status == "PARTIAL_TP1_DONE"
        assert (
            command.account_id, command.provider_id, command.feed_id,
            command.user_id, command.signal_id, command.approval_id,
        ) == original_origin, "Concurrent callbacks changed the approved command origin"
        assert execution.executed_symbol == "XAUUSD"
        assert execution.executed_direction == "BUY"
        assert session.query(models.TradeManagementEvent).filter(
            models.TradeManagementEvent.command_id == command_id
        ).count() == 1
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "BROKER_RECONCILIATION_MATCHED",
            models.AuditLog.entity_id == command_id,
        ).count() == 1
        assert session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "MANAGEMENT_EVENT",
        ).count() == 1
        assert crud.verify_audit_chain(session)["valid"]
