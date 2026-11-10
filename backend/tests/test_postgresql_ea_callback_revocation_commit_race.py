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


@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
def test_postgresql_waiting_callback_rechecks_revocation_after_lock_release(
    client, db, monkeypatch, revocation_kind
):
    """An old-key callback waiting on a row lock must be denied after revocation.

    The revoking session first flushes an uncommitted licence rotation or
    customer deactivation. The callback resolves the previously committed
    key, then attempts its customer FOR SHARE lock. PostgreSQL pg_stat_activity
    confirms the actual lock wait before revocation commits. The resumed
    callback must recheck both key and ACTIVE status, writing no receipt.

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

    revocation_locked = Event()
    commit_revocation = Event()
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

        def revoke_but_hold_customer_row():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990023")
                assert customer is not None
                if revocation_kind == "rotation":
                    replacement = crud.issue_license(session, customer)
                else:
                    assert revocation_kind == "deactivation"
                    crud.set_user_status(session, customer, "INACTIVE")
                    replacement = None
                session.flush()  # UPDATE locks User before the callback SELECT.
                revocation_locked.set()
                assert commit_revocation.wait(timeout=12), "Revocation commit not released"
                session.commit()
                return replacement

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
            revoking = workers.submit(revoke_but_hold_customer_row)
            try:
                assert revocation_locked.wait(timeout=8), "Revocation row UPDATE not flushed"
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
                commit_revocation.set()

            replacement = revoking.result(timeout=22)
            if revocation_kind == "rotation":
                assert replacement is not None and replacement != old_key
            else:
                assert replacement is None
            assert old_callback.result(timeout=22) == 403, (
                "Callback authorized under old key after revocation committed"
            )

        with SessionLocal() as session:
            customer = crud.get_user_by_telegram(session, "990023")
            assert customer is not None
            if revocation_kind == "rotation":
                assert customer.status == "ACTIVE"
                assert crud.get_user_by_license(session, old_key) is None
            else:
                # Unlike rotation, deactivation must deny a STILL-matching key.
                assert customer.status == "INACTIVE"
                assert crud.get_user_by_license(session, old_key) is not None
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

        # Restore the real resolver: the barrier stub assumes the old key is
        # valid before commit, which is deliberately false after deactivation.
        monkeypatch.setattr(crud, "resolve_ea_user", original_resolve)
        # Rotation accepts only its replacement. Deactivation keeps the same
        # key hash but must refuse even a later, non-racing callback.
        accepted = client.post(
            f"/commands/{command_id}/received",
            json={},
            headers={
                **EA_HEADERS,
                "X-SG-License-Key": replacement or old_key,
            },
        )
        if revocation_kind == "rotation":
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["status"] == "received"
        else:
            assert accepted.status_code == 403, accepted.text
    finally:
        let_callback_lock.set()
        commit_revocation.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


@pytest.mark.parametrize("conflicting_retry", (False, True))
def test_postgresql_management_retry_cannot_audit_after_licence_revocation(
    client, db, monkeypatch, conflicting_retry
):
    """Witness an actual unique idempotency-key collision and rollback race.

    Two synthetic callbacks report the same management event. After the
    winning event commits, the old-key retry hits the real PostgreSQL unique
    constraint. The losing callback must retain customer authorization through
    its subsequent duplicate-or-conflict audit commit, even if another transaction
    attempts to rotate the licence at that instant.

    This is a must-pass PostgreSQL serialization regression. Setup, SQL,
    timeout and fixture failures are not permitted to masquerade as safety.
    There is no broker, EA, Telegram transport, external credential or order.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL uniqueness and independent sessions")

    from threading import local
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.schemas import ManagementEventRequest

    owner = register_user(client, "990024")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990024"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True

    role = local()
    before_insert = Event()
    allow_insert = Event()
    after_rollback = Event()
    allow_recovery = Event()
    rotation_started = Event()
    rotated = Event()
    original_next_id = crud._next_id
    original_recovery = crud._existing_management_event_or_conflict

    def gate_first_event_insert(session, model):
        if (
            model is models.TradeManagementEvent
            and getattr(role, "name", None) == "old-key"
        ):
            before_insert.set()
            assert allow_insert.wait(timeout=15), "Old-key insert not released"
        return original_next_id(session, model)

    def gate_integrity_retry(session, command, existing, payload, *, raced=False):
        if raced and getattr(role, "name", None) == "old-key":
            after_rollback.set()
            assert allow_recovery.wait(timeout=15), "Retry audit not released"
        return original_recovery(session, command, existing, payload, raced=raced)

    monkeypatch.setattr(crud, "_next_id", gate_first_event_insert)
    monkeypatch.setattr(
        crud, "_existing_management_event_or_conflict", gate_integrity_retry
    )

    try:
        headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        polled = client.get("/commands/pending", headers=headers)
        assert polled.status_code == 200, polled.text
        command = polled.json()["command"]
        assert command is not None
        command_id = command["command_id"]
        payload = ManagementEventRequest(
            event_type="TP1_REACHED", result="PENDING", stage="SYNTHETIC",
            price=2345.0 if conflicting_retry else None,
        )
        winning_payload = ManagementEventRequest(
            event_type="TP1_REACHED", result="PENDING", stage="SYNTHETIC"
        )

        def report(incoming_role):
            role.name = incoming_role
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                try:
                    response = command_routes.report_management_event(
                        command_id,
                        payload if incoming_role == "old-key" else winning_payload,
                        x_sg_license_key=owner["license_key"],
                        db=session,
                        _ea="offline-test",
                    )
                    return response.status
                except HTTPException as exc:
                    return exc.status_code

        def rotate_licence():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990024")
                assert customer is not None
                rotation_started.set()
                assert crud.issue_license(session, customer) != owner["license_key"]
                session.commit()
                rotated.set()

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_key_future = workers.submit(report, "old-key")
            try:
                assert before_insert.wait(timeout=8), (
                    "Old-key callback never reached first event insert"
                )
                winner_future = workers.submit(report, "winner")
                assert winner_future.result(timeout=22) == "ok", (
                    "Winner failed to commit the competing management event"
                )
                allow_insert.set()
                assert after_rollback.wait(timeout=8), (
                    "No actual PostgreSQL uniqueness collision/retry was reached"
                )
                rotating_future = workers.submit(rotate_licence)
                assert rotation_started.wait(timeout=8), (
                    "Rotation did not reach its transaction barrier"
                )
                rotation_overtook_retry = rotated.wait(timeout=5)
            finally:
                allow_insert.set()
                allow_recovery.set()
            old_key_result = old_key_future.result(timeout=22)
            rotating_future.result(timeout=22)

        with SessionLocal() as session:
            assert crud.get_user_by_license(session, owner["license_key"]) is None
            assert session.scalar(
                select(models.TradeManagementEvent.id).where(
                    models.TradeManagementEvent.command_id == command_id
                )
            ) is not None
            assert session.query(models.TradeManagementEvent).count() == 1
            saved_event = session.scalar(
                select(models.TradeManagementEvent).where(
                    models.TradeManagementEvent.command_id == command_id
                )
            )
            assert saved_event is not None and saved_event.price is None
            expected_audit = (
                "MANAGEMENT_EVENT_CONFLICT" if conflicting_retry
                else "DUPLICATE_MANAGEMENT_EVENT_IGNORED"
            )
            retry_audits = session.scalars(
                select(models.AuditLog).where(
                    models.AuditLog.event_type == expected_audit,
                    models.AuditLog.entity_id == command_id,
                )
            ).all()
            assert len(retry_audits) == 1, (
                "Exactly one duplicate/conflict retry audit should commit"
            )
            assert session.query(models.Execution).count() == 0

        assert old_key_result == (409 if conflicting_retry else "duplicate_ignored")
        assert not rotation_overtook_retry, (
            "Licence rotation committed while the old-key management retry "
            "was waiting to write its duplicate audit"
        )
    finally:
        allow_insert.set()
        allow_recovery.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
def test_postgresql_pending_poll_rechecks_revocation_before_delivery(
    client, db, monkeypatch, revocation_kind
):
    """Expose a distinct old-credential pending-poll race with real PG commits.

    A synthetic EA poll authenticates with an initially valid licence and
    blocks immediately before claiming its pending command. A separate PG
    transaction then commits licence rotation or customer deactivation.
    Delivery using the old key must fail closed and must leave the command
    pending. This is NOT an EA, broker, order or external-pilot receipt.

    Both cases are must-pass security regressions. Setup errors, SQL failures
    or timeouts must fail the job, not count as a successful denial.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from sqlalchemy import select

    owner = register_user(client, "990025")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990025"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    with SessionLocal() as inspect:
        staged = inspect.scalar(
            select(models.Command).where(
                models.Command.signal_id == signal["id"],
                models.Command.user_id == owner["id"],
            )
        )
        assert staged is not None and staged.status == "PENDING"
        command_id = staged.id

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True

    resolved_before_claim = Event()
    resume_poll = Event()
    original_resolver = crud.resolve_ea_user

    def gate_after_initial_licence_lookup(session, user_id=None, license_key=None):
        user = original_resolver(
            session, user_id=user_id, license_key=license_key
        )
        assert user is not None and user.id == owner["id"], (
            "Wrong customer passed the initial licence lookup"
        )
        resolved_before_claim.set()
        assert resume_poll.wait(timeout=15), "Staged poll never resumed"
        return user

    monkeypatch.setattr(
        crud, "resolve_ea_user", gate_after_initial_licence_lookup
    )

    try:
        def old_licence_poll():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                return command_routes.pending_command(
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                )

        def commit_revocation():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990025")
                assert customer is not None
                if revocation_kind == "rotation":
                    replacement = crud.issue_license(session, customer)
                    assert replacement != owner["license_key"]
                else:
                    assert revocation_kind == "deactivation"
                    crud.set_user_status(session, customer, "INACTIVE")
                session.commit()

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_poll = workers.submit(old_licence_poll)
            try:
                assert resolved_before_claim.wait(timeout=8), (
                    "Old licence did not resolve before the staged claim"
                )
                revoke = workers.submit(commit_revocation)
                revoke.result(timeout=22)  # Must COMMIT before old poll proceeds.
                assert not old_poll.done(), (
                    "Old poll escaped the before-claim synchronization gate"
                )
            finally:
                resume_poll.set()
            response = old_poll.result(timeout=22)

        with SessionLocal() as inspect:
            customer = crud.get_user_by_telegram(inspect, "990025")
            assert customer is not None
            if revocation_kind == "rotation":
                assert crud.get_user_by_license(inspect, owner["license_key"]) is None
                assert customer.status == "ACTIVE"
            else:
                assert customer.status == "INACTIVE"
                assert crud.get_user_by_license(inspect, owner["license_key"]) is not None

            command = crud.get_command(inspect, command_id)
            assert command is not None

            assert response.command is None, (
                f"Revoked {revocation_kind} licence must not receive pending command"
            )
            assert command.status == "PENDING", (
                "A revoked poll must not consume a pending command"
            )
    finally:
        resume_poll.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


def test_postgresql_pending_poll_claim_holds_customer_lock_until_commit(
    client, db, monkeypatch
):
    """A valid poll must commit its claim before a concurrent licence rotation.

    The poll pauses after acquiring its hosted customer FOR SHARE lock but
    before touching the command. A separate PostgreSQL session attempts to
    rotate the same customer licence. Observe an actual pg_stat_activity Lock
    wait and require the poll's command/audit commit to finish before rotation.
    All identities and commands are synthetic; no EA, broker or order is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL two-transaction lock observation")

    from sqlalchemy import select, text
    from time import monotonic, sleep

    owner = register_user(client, "990026")
    signal = create_signal(client, VALID)
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990026"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    with SessionLocal() as inspect:
        command = inspect.scalar(
            select(models.Command).where(
                models.Command.signal_id == signal["id"],
                models.Command.user_id == owner["id"],
            )
        )
        assert command is not None and command.status == "PENDING"
        command_id = command.id

    previous_crud_mode = crud.settings.require_license
    previous_route_mode = command_routes.settings.require_license
    crud.settings.require_license = True
    command_routes.settings.require_license = True

    customer_locked = Event()
    release_poll = Event()
    revoke_started = Event()
    revocation_committed = Event()
    revoker_pid = {}
    original_claim = crud.get_pending_command_for_user

    def hold_before_claim(session, user_id):
        assert user_id == owner["id"]
        customer_locked.set()
        assert release_poll.wait(timeout=12), "Poll lock/claim barrier timed out"
        return original_claim(session, user_id)

    monkeypatch.setattr(crud, "get_pending_command_for_user", hold_before_claim)

    try:
        def poll_with_old_licence():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                return command_routes.pending_command(
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                )

        def rotate_after_poll_locks_customer():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                revoker_pid["pid"] = session.connection().exec_driver_sql(
                    "SELECT pg_backend_pid()"
                ).scalar_one()
                customer = crud.get_user_by_telegram(session, "990026")
                assert customer is not None
                revoke_started.set()
                replacement = crud.issue_license(session, customer)
                session.commit()
                revocation_committed.set()
                return replacement

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_poll = workers.submit(poll_with_old_licence)
            try:
                assert customer_locked.wait(timeout=8), (
                    "Poll never acquired its customer lock before command claim"
                )
                revoking = workers.submit(rotate_after_poll_locks_customer)
                assert revoke_started.wait(timeout=8), "Revocation did not begin"
                waiting_on_lock = False
                with SessionLocal() as observer:
                    deadline = monotonic() + 6
                    while monotonic() < deadline:
                        wait_type = observer.execute(
                            text(
                                "SELECT wait_event_type FROM pg_stat_activity "
                                "WHERE pid = :pid"
                            ),
                            {"pid": revoker_pid["pid"]},
                        ).scalar_one_or_none()
                        if wait_type == "Lock":
                            waiting_on_lock = True
                            break
                        sleep(0.05)
                assert waiting_on_lock, (
                    "Licence rotation never waited on the poll customer row lock"
                )
                assert not revocation_committed.is_set(), (
                    "Licence rotation committed ahead of the pending poll claim"
                )
            finally:
                release_poll.set()
            response = old_poll.result(timeout=22)
            replacement = revoking.result(timeout=22)

        assert response.command is not None
        assert response.command.command_id == command_id
        assert replacement != owner["license_key"]

        with SessionLocal() as inspect:
            command = crud.get_command(inspect, command_id)
            assert command is not None and command.status == "SENT_TO_EA"
            assert crud.get_user_by_license(inspect, owner["license_key"]) is None
            assert crud.get_user_by_license(inspect, replacement) is not None
            delivered = inspect.scalars(
                select(models.AuditLog).where(
                    models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                    models.AuditLog.entity_id == command_id,
                )
            ).all()
            assert len(delivered) == 1, (
                "The authorised poll must commit exactly one delivery audit"
            )
    finally:
        release_poll.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode
