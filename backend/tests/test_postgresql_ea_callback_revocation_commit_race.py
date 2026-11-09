"""Offline PostgreSQL witness for an EA callback versus customer licence rotation.

This is a synthetic concurrency regression, not external security acceptance.
The test uses fabricated customers and DB sessions only: no HTTP transport,
MT5, broker, orders, external credentials or real customer data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app import crud, models
from app.database import SessionLocal
from app.routes import commands as command_routes
from app.schemas import CommandReceivedRequest

from .conftest import EA_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"



def test_postgresql_callback_receipt_cannot_overtake_committed_licence_rotation(
    client, db, monkeypatch
):
    """Prove that a callback holds authorization until its commit.

    Transaction A authorizes a fabricated, already claimed command using the
    current customer licence and pauses before adding the audit receipt.
    Transaction B attempts to rotate the licence in another database session.
    Rotation must not commit until A has finished its acknowledgement commit.
    On PostgreSQL, the callback's shared customer-row lock enforces that order.

    The two-session barrier uses synthetic data only, never an actual EA/broker.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    owner = register_user(client, "990021")
    signal = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990021"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["result"] == "APPROVED"

    former_crud_mode = crud.settings.require_license
    former_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True
    resolved = Event()
    release_callback = Event()
    rotated = Event()
    original_resolver = command_routes._get_authorized_callback_command

    def hold_after_resolution(session, command_id, license_key):
        command = original_resolver(session, command_id, license_key)
        resolved.set()
        assert release_callback.wait(timeout=15), (
            "Timed out before the staged callback could resume"
        )
        return command

    monkeypatch.setattr(
        command_routes, "_get_authorized_callback_command", hold_after_resolution
    )

    try:
        old_headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        poll = client.get("/commands/pending", headers=old_headers)
        assert poll.status_code == 200, poll.text
        issued = poll.json()["command"]
        assert issued is not None
        command_id = issued["command_id"]

        def acknowledge_in_independent_transaction():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                return command_routes.command_received(
                    command_id,
                    CommandReceivedRequest(),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                )

        def rotate_in_independent_transaction():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL lock_timeout = '8s'"
                )
                account = crud.get_user_by_telegram(session, "990021")
                assert account is not None
                replacement = crud.issue_license(session, account)
                assert replacement != owner["license_key"]
                session.commit()
                rotated.set()

        with ThreadPoolExecutor(max_workers=2) as workers:
            callback_future = workers.submit(acknowledge_in_independent_transaction)
            try:
                assert resolved.wait(timeout=8), (
                    "Callback did not reach the post-authorization barrier"
                )
                rotate_future = workers.submit(rotate_in_independent_transaction)
                rotation_overtook_callback = rotated.wait(timeout=2.5)
            finally:
                release_callback.set()
            reply = callback_future.result(timeout=22)
            rotate_future.result(timeout=22)

        with SessionLocal() as session:
            command = crud.get_command(session, command_id)
            assert command is not None and command.status == "SENT_TO_EA"
            assert crud.get_user_by_license(session, owner["license_key"]) is None
            acknowledgements = (
                session.query(models.AuditLog)
                .filter(
                    models.AuditLog.event_type == "COMMAND_RECEIVED_BY_EA",
                    models.AuditLog.entity_id == command_id,
                )
                .count()
            )
            assert session.query(models.Execution).count() == 0
            assert session.query(models.TradeManagementEvent).count() == 0

        # This implementation serializes a customer callback and key rotation:
        # the rotating transaction must wait until the callback has committed.
        # An old-key callback cannot commit AFTER a completed key rotation.
        assert not rotation_overtook_callback, (
            "Licence rotation committed while the old-key callback was still pending"
        )
        assert reply.status == "received"
        assert acknowledgements == 1
    finally:
        release_callback.set()
        crud.settings.require_license = former_crud_mode
        command_routes.settings.require_license = former_route_mode


def test_postgresql_execution_retry_rechecks_license_after_integrity_rollback(
    client, db, monkeypatch
):
    """Exercise the actual duplicate-Execution INSERT race, not a fake rollback.

    An old-key execution request pauses after its initial execution lookup.
    Another request commits the same fabricated FAILED result. The first
    request then collides with the real unique(command_id) database constraint,
    rolls back, and reaches the raced-retry audit path. Rotate the licence
    between that rollback and audit. A revoked key must never commit that
    subsequent audit receipt. No real broker, EA or network calls are made.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL uniqueness and independent sessions")

    from threading import local
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.schemas import ExecutionRequest

    owner = register_user(client, "990022")
    signal = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990022"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["result"] == "APPROVED"

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True

    pre_insert = Event()
    allow_insert = Event()
    after_rollback = Event()
    allow_recovery = Event()
    rotation_started = Event()
    rotated = Event()
    role = local()
    original_next_id = crud._next_id
    original_recovery = crud._existing_execution_or_conflict

    def gate_first_insert(session, model):
        if model is models.Execution and getattr(role, "name", None) == "old-key":
            pre_insert.set()
            assert allow_insert.wait(timeout=15), "Old-key insert was not released"
        return original_next_id(session, model)

    def gate_actual_integrity_recovery(session, command, existing, payload, *, raced=False):
        if raced and getattr(role, "name", None) == "old-key":
            after_rollback.set()
            assert allow_recovery.wait(timeout=15), (
                "Old-key rolled-back retry was not released"
            )
        return original_recovery(session, command, existing, payload, raced=raced)

    monkeypatch.setattr(crud, "_next_id", gate_first_insert)
    monkeypatch.setattr(crud, "_existing_execution_or_conflict", gate_actual_integrity_recovery)

    try:
        headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        polled = client.get("/commands/pending", headers=headers)
        assert polled.status_code == 200, polled.text
        command = polled.json()["command"]
        assert command is not None
        command_id = command["command_id"]
        payload = ExecutionRequest(status="FAILED", error_code="OFFLINE_REJECT")

        def report(role_name):
            role.name = role_name
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                try:
                    result = command_routes.report_execution(
                        command_id,
                        payload,
                        x_sg_license_key=owner["license_key"],
                        db=session,
                        _ea="offline-test",
                    )
                    return result.status
                except HTTPException as exc:
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_key = workers.submit(report, "old-key")
            try:
                assert pre_insert.wait(timeout=8), (
                    "Old-key report did not reach its first execution INSERT"
                )
                winner = workers.submit(report, "winner")
                assert winner.result(timeout=22) == "ok", (
                    "Competing execution did not commit before old-key retry"
                )
                allow_insert.set()
                assert after_rollback.wait(timeout=8), (
                    "Actual PostgreSQL unique constraint did not trigger "
                    "the IntegrityError rollback/recovery branch"
                )

                def rotate_in_independent_transaction():
                    with SessionLocal() as rotation:
                        rotation.connection().exec_driver_sql(
                            "SET LOCAL statement_timeout = '12s'"
                        )
                        account = crud.get_user_by_telegram(rotation, "990022")
                        assert account is not None
                        rotation_started.set()
                        assert crud.issue_license(rotation, account) != owner["license_key"]
                        rotation.commit()
                        rotated.set()

                rotator = workers.submit(rotate_in_independent_transaction)
                assert rotation_started.wait(timeout=8), (
                    "Licence rotation did not reach its transaction barrier"
                )
                rotation_overtook_retry = rotated.wait(timeout=2.5)
            finally:
                allow_insert.set()
                allow_recovery.set()
            old_key_outcome = old_key.result(timeout=22)
            rotator.result(timeout=22)

        with SessionLocal() as session:
            assert crud.get_user_by_license(session, owner["license_key"]) is None
            assert session.scalar(
                select(models.Execution).where(
                    models.Execution.command_id == command_id
                )
            ) is not None
            assert session.query(models.Execution).count() == 1
            assert session.query(models.TradeManagementEvent).count() == 0
            audits = list(
                session.scalars(
                    select(models.AuditLog)
                    .where(models.AuditLog.entity_id.in_([command_id, owner["id"]]))
                    .order_by(models.AuditLog.created_at, models.AuditLog.id)
                )
            )
            rotations = [
                a for a in audits
                if a.event_type == "LICENSE_ISSUED" and a.entity_id == owner["id"]
            ]
            retry_audits = [
                a for a in audits
                if a.event_type == "DUPLICATE_EXECUTION_REPORT_IGNORED"
                and a.entity_id == command_id
            ]
            assert rotations, "Licence rotation receipt must be committed"
            assert not rotation_overtook_retry, (
                "Licence rotation committed while the old-key retry was still "
                "waiting to write its duplicate audit"
            )
            assert old_key_outcome == "duplicate_ignored"
            assert len(retry_audits) == 1
            assert retry_audits[0].created_at <= rotations[-1].created_at, (
                "A retry audit must precede the committed licence rotation"
            )
    finally:
        allow_insert.set()
        allow_recovery.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


def test_postgresql_waiting_callback_rechecks_rotation_after_lock_release(
    client, db, monkeypatch
):
    """An old-key callback waiting on a row lock must be denied after rotation.

    The rotating session first flushes an uncommitted licence replacement.
    The callback resolves the previously committed key, then attempts its
    customer FOR SHARE lock. PostgreSQL pg_stat_activity confirms the actual
    lock wait before the rotation is committed. The resumed callback must
    recheck the key against the newly committed row and write no receipt.

    Fabricated account/command and isolated PostgreSQL only; no live EA,
    broker, real customer, signal transport or order is involved.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row-lock recheck")

    from fastapi import HTTPException
    from sqlalchemy import select, text
    from time import monotonic, sleep

    owner = register_user(client, "990023")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990023"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True

    rotation_locked = Event()
    commit_rotation = Event()
    old_key_resolved = Event()
    let_callback_lock = Event()
    callback_pid_ready = Event()
    callback_pid: dict[str, int] = {}
    old_key = owner["license_key"]
    original_resolve = crud.resolve_ea_user

    def hold_after_old_key_lookup(session, *args, **kwargs):
        user = original_resolve(session, *args, **kwargs)
        if kwargs.get("license_key") == old_key:
            assert user is not None, "Old key should resolve before rotation commit"
            old_key_resolved.set()
            assert let_callback_lock.wait(timeout=12), "Callback lock attempt not released"
        return user

    try:
        original_headers = {**EA_HEADERS, "X-SG-License-Key": old_key}
        polled = client.get("/commands/pending", headers=original_headers)
        assert polled.status_code == 200, polled.text
        command = polled.json()["command"]
        assert command is not None
        command_id = command["command_id"]

        monkeypatch.setattr(crud, "resolve_ea_user", hold_after_old_key_lookup)

        def rotate_but_hold_customer_row():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990023")
                assert customer is not None
                new_key = crud.issue_license(session, customer)
                session.flush()  # UPDATE locks User before the callback SELECT.
                rotation_locked.set()
                assert commit_rotation.wait(timeout=12), "Rotation commit not released"
                session.commit()
                return new_key

        def callback_waiting_for_customer_lock():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                callback_pid["pid"] = session.connection().exec_driver_sql(
                    "SELECT pg_backend_pid()"
                ).scalar_one()
                callback_pid_ready.set()
                try:
                    command_routes.command_received(
                        command_id,
                        CommandReceivedRequest(),
                        x_sg_license_key=old_key,
                        db=session,
                        _ea="offline-test",
                    )
                except HTTPException as exc:
                    return exc.status_code
                return 200

        with ThreadPoolExecutor(max_workers=2) as workers:
            rotating = workers.submit(rotate_but_hold_customer_row)
            try:
                assert rotation_locked.wait(timeout=8), "Rotation row UPDATE not flushed"
                old_callback = workers.submit(callback_waiting_for_customer_lock)
                assert callback_pid_ready.wait(timeout=8), "No callback backend PID"
                assert old_key_resolved.wait(timeout=8), "Old key did not resolve"
                let_callback_lock.set()

                # Observe the *real* PostgreSQL lock wait, not a sleep-only race.
                waiting_on_lock = False
                with SessionLocal() as observer:
                    deadline = monotonic() + 6
                    while monotonic() < deadline:
                        wait_type = observer.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": callback_pid["pid"]},
                        ).scalar_one_or_none()
                        if wait_type == "Lock":
                            waiting_on_lock = True
                            break
                        sleep(0.05)
                assert waiting_on_lock, (
                    "Callback never waited on PostgreSQL customer row lock"
                )
                assert not old_callback.done(), "Callback escaped the lock wait"
            finally:
                let_callback_lock.set()
                commit_rotation.set()

            replacement = rotating.result(timeout=22)
            assert replacement != old_key
            assert old_callback.result(timeout=22) == 403, (
                "Callback authorized under old key after rotation committed"
            )

        with SessionLocal() as session:
            assert crud.get_user_by_license(session, old_key) is None
            assert crud.get_command(session, command_id).status == "SENT_TO_EA"
            assert (
                session.scalar(
                    select(models.AuditLog.id).where(
                        models.AuditLog.event_type == "COMMAND_RECEIVED_BY_EA",
                        models.AuditLog.entity_id == command_id,
                    )
                )
                is None
            )
            assert session.query(models.Execution).count() == 0
            assert session.query(models.TradeManagementEvent).count() == 0

        # Positive control: the newly committed credential can acknowledge.
        accepted = client.post(
            f"/commands/{command_id}/received",
            json={},
            headers={**EA_HEADERS, "X-SG-License-Key": replacement},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "received"
    finally:
        let_callback_lock.set()
        commit_rotation.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode
