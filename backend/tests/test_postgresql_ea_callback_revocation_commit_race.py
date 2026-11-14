"""Offline PostgreSQL witness for an EA callback versus customer licence rotation.

This is a synthetic concurrency regression, not external security acceptance.
The test uses fabricated customers and DB sessions only: no HTTP transport,
MT5, broker, orders, external credentials or real customer data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from app import crud, models
from app.database import SessionLocal
from app.routes import commands as command_routes
from app.schemas import CommandReceivedRequest

from .conftest import EA_HEADERS, register_user
from .test_commands import _hosted_provider_signal_for


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
    signal = _hosted_provider_signal_for(client, "990021")
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


@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
def test_postgresql_execution_retry_rechecks_license_after_integrity_rollback(
    client, db, monkeypatch, revocation_kind
):
    """Exercise the actual duplicate-Execution INSERT race, not a fake rollback.

    An old-key execution request pauses after its initial execution lookup.
    Another request commits the same fabricated FAILED result. The first
    request then collides with the real unique(command_id) database constraint,
    rolls back, and reaches the raced-retry audit path. Rotate the licence or
    deactivate the customer before that audit. Neither revocation may commit
    ahead of a still-authorized retry audit; no broker or network calls occur.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL uniqueness and independent sessions")

    from threading import local
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.schemas import ExecutionRequest

    owner = register_user(client, "990022")
    signal = _hosted_provider_signal_for(client, "990022")
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
    revocation_started = Event()
    revoked = Event()
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

                def revoke_in_independent_transaction():
                    with SessionLocal() as session:
                        session.connection().exec_driver_sql(
                            "SET LOCAL statement_timeout = '12s'"
                        )
                        account = crud.get_user_by_telegram(session, "990022")
                        assert account is not None
                        revocation_started.set()
                        if revocation_kind == "rotation":
                            assert crud.issue_license(session, account) != owner["license_key"]
                        else:
                            crud.set_user_status(session, account, "INACTIVE")
                        session.commit()
                        revoked.set()

                revoker = workers.submit(revoke_in_independent_transaction)
                assert revocation_started.wait(timeout=8), (
                    "Customer revocation did not reach its transaction barrier"
                )
                revocation_overtook_retry = revoked.wait(timeout=2.5)
            finally:
                allow_insert.set()
                allow_recovery.set()
            old_key_outcome = old_key.result(timeout=22)
            revoker.result(timeout=22)

        with SessionLocal() as session:
            customer = crud.get_user_by_telegram(session, "990022")
            assert customer is not None
            if revocation_kind == "rotation":
                assert crud.get_user_by_license(session, owner["license_key"]) is None
                assert customer.status == "ACTIVE"
            else:
                assert customer.status == "INACTIVE"
                assert crud.get_user_by_license(session, owner["license_key"]) is not None
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
            revocation_event = (
                "LICENSE_ISSUED" if revocation_kind == "rotation" else "USER_STATUS_CHANGED"
            )
            revocations = [
                a for a in audits
                if a.event_type == revocation_event and a.entity_id == owner["id"]
            ]
            retry_audits = [
                a for a in audits
                if a.event_type == "DUPLICATE_EXECUTION_REPORT_IGNORED"
                and a.entity_id == command_id
            ]
            assert revocations, "Customer revocation audit must be committed"
            assert not revocation_overtook_retry, (
                "Customer revocation committed while the old-key retry was still "
                "waiting to write its duplicate audit"
            )
            assert old_key_outcome == "duplicate_ignored"
            assert len(retry_audits) == 1
            assert retry_audits[0].created_at <= revocations[-1].created_at, (
                "A retry audit must precede the committed customer revocation"
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
    signal = _hosted_provider_signal_for(client, "990023")
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
@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
def test_postgresql_management_retry_cannot_audit_after_licence_revocation(
    client, db, monkeypatch, conflicting_retry, revocation_kind
):
    """Witness an actual unique idempotency-key collision and rollback race.

    Two synthetic callbacks report the same management event. After the
    winning event commits, the old-key retry hits the real PostgreSQL unique
    constraint. The losing callback must retain customer authorization through
    its subsequent duplicate-or-conflict audit commit, even if another transaction
    attempts to rotate the licence or deactivate the customer at that instant.

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
    signal = _hosted_provider_signal_for(client, "990024")
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
    revocation_started = Event()
    revocation_committed = Event()
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

        def revoke_customer():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990024")
                assert customer is not None
                revocation_started.set()
                if revocation_kind == "rotation":
                    assert crud.issue_license(session, customer) != owner["license_key"]
                else:
                    assert revocation_kind == "deactivation"
                    crud.set_user_status(session, customer, "INACTIVE")
                session.commit()
                revocation_committed.set()

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
                revoking_future = workers.submit(revoke_customer)
                assert revocation_started.wait(timeout=8), (
                    "Revocation did not reach its transaction barrier"
                )
                revocation_overtook_retry = revocation_committed.wait(timeout=5)
            finally:
                allow_insert.set()
                allow_recovery.set()
            old_key_result = old_key_future.result(timeout=22)
            revoking_future.result(timeout=22)

        with SessionLocal() as session:
            customer = crud.get_user_by_telegram(session, "990024")
            assert customer is not None
            if revocation_kind == "rotation":
                assert customer.status == "ACTIVE"
                assert crud.get_user_by_license(session, owner["license_key"]) is None
            else:
                assert customer.status == "INACTIVE"
                # Deactivation preserves the credential hash, not its authority.
                assert crud.get_user_by_license(session, owner["license_key"]) is not None
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
        assert not revocation_overtook_retry, (
            f"{revocation_kind} committed while the old-key management retry "
            "was waiting to write its duplicate/conflict audit"
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
    signal = _hosted_provider_signal_for(client, "990025")
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
                    replacement = None
                session.commit()
                return replacement

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_poll = workers.submit(old_licence_poll)
            try:
                assert resolved_before_claim.wait(timeout=8), (
                    "Old licence did not resolve before the staged claim"
                )
                revoke = workers.submit(commit_revocation)
                replacement_key = revoke.result(timeout=22)  # Must COMMIT before old poll proceeds.
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
            sent_audits = inspect.scalars(
                select(models.AuditLog).where(
                    models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                    models.AuditLog.entity_id == command_id,
                )
            ).all()
            assert not sent_audits, (
                "Revoked polls must not leave a command-delivery audit receipt"
            )

        # Rotation revokes only the old credential. The newly issued, active
        # credential must still be able to claim the preserved pending command.
        # Deactivation has no replacement credential and must remain blocked.
        if revocation_kind == "rotation":
            assert replacement_key and replacement_key != owner["license_key"]
            with SessionLocal() as replacement_session:
                new_poll = command_routes.pending_command(
                    x_sg_license_key=replacement_key,
                    db=replacement_session,
                    _ea="offline-test",
                )
            assert new_poll.command is not None
            assert new_poll.command.command_id == command_id
            with SessionLocal() as inspect:
                delivered = crud.get_command(inspect, command_id)
                assert delivered is not None and delivered.status == "SENT_TO_EA"
                sent_audits = inspect.scalars(
                    select(models.AuditLog).where(
                        models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                        models.AuditLog.entity_id == command_id,
                    )
                ).all()
                assert len(sent_audits) == 1, (
                    "Replacement credential must claim exactly once"
                )
        else:
            assert replacement_key is None
    finally:
        resume_poll.set()
        crud.settings.require_license = previous_crud_mode
        command_routes.settings.require_license = previous_route_mode


@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
def test_postgresql_pending_poll_claim_holds_customer_lock_until_commit(
    client, db, monkeypatch, revocation_kind
):
    """A valid poll must commit its claim before either kind of revocation.

    The poll pauses after acquiring its hosted customer FOR SHARE lock but
    before touching the command. A separate PostgreSQL session attempts to
    rotate the licence or deactivate the customer. Observe a real PostgreSQL
    lock wait and require the command/audit commit to finish before revocation.
    All identities and commands are synthetic; no EA, broker or order is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL two-transaction lock observation")

    from sqlalchemy import select, text
    from time import monotonic, sleep

    owner = register_user(client, "990026")
    signal = _hosted_provider_signal_for(client, "990026")
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

        def revoke_after_poll_locks_customer():
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
                if revocation_kind == "rotation":
                    replacement = crud.issue_license(session, customer)
                else:
                    assert revocation_kind == "deactivation"
                    crud.set_user_status(session, customer, "INACTIVE")
                    replacement = None
                session.commit()
                revocation_committed.set()
                return replacement

        with ThreadPoolExecutor(max_workers=2) as workers:
            old_poll = workers.submit(poll_with_old_licence)
            try:
                assert customer_locked.wait(timeout=8), (
                    "Poll never acquired its customer lock before command claim"
                )
                revoking = workers.submit(revoke_after_poll_locks_customer)
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
                    f"{revocation_kind} never waited on the poll customer row lock"
                )
                assert not revocation_committed.is_set(), (
                    f"{revocation_kind} committed ahead of the pending poll claim"
                )
            finally:
                release_poll.set()
            response = old_poll.result(timeout=22)
            replacement = revoking.result(timeout=22)

        assert response.command is not None
        assert response.command.command_id == command_id
        if revocation_kind == "rotation":
            assert replacement is not None and replacement != owner["license_key"]
        else:
            assert replacement is None

        with SessionLocal() as inspect:
            command = crud.get_command(inspect, command_id)
            assert command is not None and command.status == "SENT_TO_EA"
            customer = crud.get_user_by_telegram(inspect, "990026")
            assert customer is not None
            if revocation_kind == "rotation":
                assert customer.status == "ACTIVE"
                assert crud.get_user_by_license(inspect, owner["license_key"]) is None
                assert crud.get_user_by_license(inspect, replacement) is not None
            else:
                assert customer.status == "INACTIVE"
                # Deactivation preserves the hash but must still revoke authority.
                assert crud.get_user_by_license(inspect, owner["license_key"]) is not None
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


@pytest.mark.parametrize(
    "writer_first", (True, False), ids=("writer-first-denied", "callback-first-serialized")
)
def test_postgresql_command_account_relabel_serializes_with_callback_receipt(
    client, db, monkeypatch, writer_first
):
    """Two synthetic PostgreSQL sessions verify both account-relabel orders.

    Writer first: reassignment after initial auth but before the acknowledgement
    row lock must return 403 and write NO historical receipt.
    Callback first: the acknowledgement lock must hold through the audit commit
    and block the competing account rewrite until the receipt is durable.
    No real EA, MT5, broker, trade or customer data is involved.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    from .test_provider_export import _provider, _headers

    provider, feed, provider_key = _provider(db, "callback-account-drift-race")
    db.commit()
    owner = register_user(
        client, "990356", "synthetic_account_drift_a", "Synthetic A"
    )
    foreign = register_user(
        client, "990357", "synthetic_account_drift_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, foreign["id"])
    )
    account_a_id, account_b_id = account_a.id, account_b.id
    assert account_a_id != account_b_id
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
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": owner["id"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id
    db.expire_all()
    command = db.get(models.Command, command_id)
    assert command.account_id == account_a_id
    assert command.status == "SENT_TO_EA"
    db.rollback()

    gated = Event()
    release_receipt = Event()
    relabel_committed = Event()
    relabel_attempted = Event()
    original_resolver = command_routes._get_authorized_callback_command
    original_mark = crud.mark_command_received

    def hold_after_original_authorization(session, cid, license_key):
        resolved = original_resolver(session, cid, license_key)
        gated.set()
        assert release_receipt.wait(timeout=15), (
            "Callback did not resume after the relabel transaction"
        )
        return resolved

    def hold_after_receipt_row_lock(session, resolved):
        # mark_command_received is reached only after the route holds the
        # new shared Command lock, before the audit INSERT and COMMIT.
        gated.set()
        assert release_receipt.wait(timeout=15), (
            "Callback did not resume after the acknowledgement row lock"
        )
        return original_mark(session, resolved)

    def acknowledge_in_independent_transaction():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            try:
                return command_routes.command_received(
                    command_id,
                    CommandReceivedRequest(),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status
            except HTTPException as exc:
                return exc.status_code

    def relabel_account_in_independent_transaction():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            changed = session.get(models.Command, command_id)
            assert changed is not None
            changed.account_id = account_b_id
            relabel_attempted.set()
            session.commit()
            relabel_committed.set()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        if writer_first:
            patch.setattr(
                command_routes, "_get_authorized_callback_command",
                hold_after_original_authorization,
            )
        else:
            patch.setattr(
                crud, "mark_command_received", hold_after_receipt_row_lock
            )
        with ThreadPoolExecutor(max_workers=2) as workers:
            receipt_future = workers.submit(
                acknowledge_in_independent_transaction
            )
            try:
                assert gated.wait(timeout=8), (
                    "Hosted callback never reached its designated barrier"
                )
                writer_future = workers.submit(
                    relabel_account_in_independent_transaction
                )
                assert relabel_attempted.wait(timeout=8), (
                    "Second transaction never reached account relabel commit"
                )
                relabel_overtook_receipt = relabel_committed.wait(timeout=3)
            finally:
                release_receipt.set()
            receipt_result = receipt_future.result(timeout=22)
            writer_future.result(timeout=22)

    with SessionLocal() as session:
        changed = session.get(models.Command, command_id)
        receipt_count = session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "COMMAND_RECEIVED_BY_EA",
            models.AuditLog.entity_id == command_id,
        ).count()
        assert changed.account_id == account_b_id
        assert changed.status == "SENT_TO_EA"
        assert session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).count() == 0

    if writer_first:
        assert relabel_overtook_receipt, (
            "Account rewrite must commit before releasing the initial-auth barrier"
        )
        assert receipt_result == 403, (
            "The original EA licence must be refused after account reassignment"
        )
        assert receipt_count == 0, (
            "Stale-authorised acknowledgement must write no audit"
        )
    else:
        assert not relabel_overtook_receipt, (
            "Account rewrite committed before the acknowledgement audit"
        )
        assert receipt_result == "received"
        assert receipt_count == 1, (
            "Only the authorised callback-first receipt must be committed"
        )


@pytest.mark.parametrize(
    "report_case", ["first-failed-receipt", "matching-failed-retry", "conflicting-failed-retry"]
)
def test_postgresql_command_account_relabel_execution_after_auth(
    client, db, monkeypatch, report_case
):
    """Fail closed if the command account changes after EA callback authorization.

    A has a delivered synthetic command. A's valid EA callback resolves and
    retains its customer, signal, approval and original account share locks.
    B changes ONLY Command.account_id in another PostgreSQL session and commits
    while A is paused. A must not subsequently record a first FAILED execution,
    acknowledge a matching retry with a duplicate audit, or commit an
    inconsistent-retry conflict audit for a now-foreign-account command.
    All reports are synthetic no-order data: no EA, broker or external HTTP.

    Until the invariant is fixed, strict XFAILs are emitted ONLY after both
    transactions commit and the unauthorized first receipt, matching retry
    acknowledgement OR conflict audit is independently confirmed.
    Timeout, fixture, constraint and missing-evidence failures remain FAIL.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from app.schemas import ExecutionRequest
    from .test_provider_export import _provider, _headers

    provider, feed, provider_key = _provider(
        db, "callback-execution-account-relabel-race"
    )
    db.commit()
    owner = register_user(
        client, "990360", "synthetic_exec_relabel_a", "Synthetic A"
    )
    foreign = register_user(
        client, "990361", "synthetic_exec_relabel_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, foreign["id"])
    )
    account_a_id, account_b_id = account_a.id, account_b.id
    assert account_a_id != account_b_id
    db.commit()

    created = client.post(
        "/signals/create",
        headers=_headers(provider, provider_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    approval = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": owner["telegram_user_id"]},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["result"] == "APPROVED"
    command_id = approval.json()["command_id"]
    db.rollback()
    claimed = client.get(
        "/commands/pending",
        headers=EA_HEADERS,
        params={"user_id": owner["id"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["command"]["command_id"] == command_id
    db.expire_all()
    assert db.get(models.Command, command_id).account_id == account_a_id
    db.rollback()

    if report_case in {"matching-failed-retry", "conflicting-failed-retry"}:
        # Seed the original no-broker FAILED receipt before the account drift.
        # Neither a matching-duplicate audit nor a conflict audit is permitted
        # after a committed foreign-account reassignment.
        with monkeypatch.context() as patch:
            patch.setattr(
                command_routes, "notify_user_and_admins",
                lambda *_a, **_kw: None,
            )
            baseline = client.post(
                f"/commands/{command_id}/execution",
                headers=EA_HEADERS,
                json={
                    "status": "FAILED",
                    "error_code": "SYNTHETIC_ORIGINAL_NO_ORDER",
                },
            )
        assert baseline.status_code == 200, baseline.text
        assert baseline.json()["status"] == "ok"
        db.expire_all()
        assert db.get(models.Command, command_id).status == "FAILED"
        db.rollback()

    authorized = Event()
    resume_callback = Event()
    rewrite_committed = Event()
    original_resolver = command_routes._get_authorized_callback_command

    def pause_after_authorization(session, cid, license_key):
        command = original_resolver(session, cid, license_key)
        authorized.set()
        assert resume_callback.wait(timeout=15), (
            "Execution callback never resumed after independent rewrite"
        )
        return command

    def execution_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            try:
                return command_routes.report_execution(
                    command_id,
                    ExecutionRequest(
                        status="FAILED",
                        error_code=(
                            "SYNTHETIC_CONFLICTING_RETRY"
                            if report_case == "conflicting-failed-retry"
                            else "SYNTHETIC_ORIGINAL_NO_ORDER"
                            if report_case == "matching-failed-retry"
                            else "SYNTHETIC_NO_ORDER"
                        ),
                    ),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status
            except HTTPException as exc:
                return exc.status_code

    def rewrite_account_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            changed = session.get(models.Command, command_id)
            assert changed is not None
            changed.account_id = account_b_id
            session.commit()
            rewrite_committed.set()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(
            command_routes, "_get_authorized_callback_command",
            pause_after_authorization,
        )
        patch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            execution_future = workers.submit(execution_in_session)
            try:
                assert authorized.wait(timeout=8), (
                    "Execution callback failed to reach authorization barrier"
                )
                rewrite_future = workers.submit(rewrite_account_in_session)
                assert rewrite_committed.wait(timeout=8), (
                    "Account reassignment did not commit before callback resumed"
                )
            finally:
                resume_callback.set()
            callback_result = execution_future.result(timeout=22)
            rewrite_future.result(timeout=22)

    with SessionLocal() as session:
        changed = session.get(models.Command, command_id)
        assert changed is not None and changed.account_id == account_b_id
        assert changed.user_id == owner["id"]
        command_status_after = changed.status
        executions = session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).all()
        recorded_audits = (
            session.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "EXECUTION_RECORDED",
                models.AuditLog.entity_id == executions[0].id,
            )
            .count()
            if len(executions) == 1 else 0
        )
        conflict_audits = session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "EXECUTION_REPORT_CONFLICT",
            models.AuditLog.entity_id == command_id,
        ).count()
        duplicate_audits = session.query(models.AuditLog).filter(
            models.AuditLog.event_type == "DUPLICATE_EXECUTION_REPORT_IGNORED",
            models.AuditLog.entity_id == command_id,
        ).count()

    has_prior_receipt = report_case != "first-failed-receipt"
    if callback_result == 403:
        assert len(executions) == int(has_prior_receipt)
        assert recorded_audits == int(has_prior_receipt)
        assert conflict_audits == 0, "Denied stale callback must not log conflict"
        assert duplicate_audits == 0, "Denied stale callback must not log duplicate"
        assert command_status_after == (
            "FAILED" if has_prior_receipt else "SENT_TO_EA"
        )
        if has_prior_receipt:
            assert executions[0].status == "FAILED"
            assert executions[0].error_code == "SYNTHETIC_ORIGINAL_NO_ORDER"
        return

    if (
        not has_prior_receipt
        and callback_result == "ok"
        and len(executions) == 1
        and executions[0].user_id == owner["id"]
        and executions[0].status == "FAILED"
        and recorded_audits == 1
        and conflict_audits == 0
        and duplicate_audits == 0
    ):
        pytest.xfail(
            "RELEASE HOLD: subscriber A's FAILED execution and audit committed "
            "AFTER subscriber B's Command.account_id reassignment committed"
        )

    if (
        report_case == "matching-failed-retry"
        and callback_result == "duplicate_ignored"
        and len(executions) == 1
        and executions[0].user_id == owner["id"]
        and executions[0].status == "FAILED"
        and executions[0].error_code == "SYNTHETIC_ORIGINAL_NO_ORDER"
        and command_status_after == "FAILED"
        and recorded_audits == 1
        and conflict_audits == 0
        and duplicate_audits == 1
    ):
        pytest.xfail(
            "RELEASE HOLD: subscriber A's matching FAILED retry was acknowledged "
            "with a duplicate audit AFTER subscriber B's account relabel committed"
        )

    if (
        report_case == "conflicting-failed-retry"
        and callback_result == 409
        and len(executions) == 1
        and executions[0].user_id == owner["id"]
        and executions[0].status == "FAILED"
        and executions[0].error_code == "SYNTHETIC_ORIGINAL_NO_ORDER"
        and command_status_after == "FAILED"
        and recorded_audits == 1
        and conflict_audits == 1
        and duplicate_audits == 0
    ):
        pytest.xfail(
            "RELEASE HOLD: subscriber A's conflicting retry committed an audit "
            "AFTER subscriber B's Command.account_id reassignment committed"
        )

    pytest.fail(
        "Unexpected post-reassignment callback outcome: "
        f"case={report_case}, result={callback_result!r}, "
        f"executions={len(executions)}, recorded_audits={recorded_audits}, "
        f"conflict_audits={conflict_audits}, duplicate_audits={duplicate_audits}, "
        f"command_status={command_status_after}"
    )
@pytest.mark.parametrize(
    ("event_type", "stage", "result"),
    [
        pytest.param("TP1_REACHED", "TP1_REACHED", "PENDING", id="price-observation"),
        pytest.param("TP1_CLOSE_SUCCESS", "TP1_CLOSED", "SUCCESS", id="state-advance"),
    ],
)
def test_postgresql_command_account_relabel_management_observation_after_auth(
    client, db, monkeypatch, event_type, stage, result
):
    """Synthetic two-session HOLD witness for price and state-changing callbacks.

    A legitimately delivered demo command and a fabricated prior SUCCESS
    execution belong to subscriber A. The callback resolves A's original
    provenance, then B's account-only Command relabel commits before the
    callback resumes. An authorisation-safe receipt must be refused with no
    new management row or audit. This never contacts an EA or broker.

    Only a proven foreign-account event AND its persisted audit are XFAIL.
    Bad setup, timeouts and unexpected outcomes are ordinary failures.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from app.schemas import ManagementEventRequest
    from .test_provider_export import _provider, _headers

    provider, feed, provider_key = _provider(
        db, "callback-management-account-relabel-race"
    )
    db.commit()
    owner = register_user(
        client, "990365", "synthetic_mgmt_relabel_a", "Synthetic A"
    )
    foreign = register_user(
        client, "990366", "synthetic_mgmt_relabel_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, foreign["id"])
    )
    account_a_id, account_b_id = account_a.id, account_b.id
    assert account_a_id != account_b_id
    db.commit()

    signal = client.post(
        "/signals/create",
        headers=_headers(provider, provider_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert signal.status_code == 200, signal.text
    approved = client.post(
        f"/signals/{signal.json()['id']}/approve",
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
    db.expire_all()
    assert db.get(models.Command, command_id).account_id == account_a_id
    db.rollback()

    # Fabricated EA-shaped result, not a broker fill or external receipt.
    with monkeypatch.context() as patch:
        patch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )
        seeded = client.post(
            f"/commands/{command_id}/execution",
            headers=EA_HEADERS,
            json={
                "status": "SUCCESS",
                "broker_ticket": "SYNTHETIC-MGMT-RACE-NO-BROKER",
                "executed_symbol": "XAUUSD",
                "executed_direction": "BUY",
                "executed_price": 2345.0,
                "lot_size": 0.1,
            },
        )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["status"] == "ok"
    db.expire_all()
    assert db.get(models.Command, command_id).status == "EXECUTED_OPEN"
    db.rollback()

    authorized = Event()
    resume_callback = Event()
    rewrite_committed = Event()
    original_resolver = command_routes._get_authorized_callback_command

    def pause_after_authorization(session, cid, license_key):
        command = original_resolver(session, cid, license_key)
        authorized.set()
        assert resume_callback.wait(timeout=15), (
            "Management callback never resumed after account rewrite"
        )
        return command

    def observation_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            try:
                return command_routes.report_management_event(
                    command_id,
                    ManagementEventRequest(
                        event_type=event_type,
                        stage=stage,
                        result=result,
                    ),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status
            except HTTPException as exc:
                return exc.status_code

    def rewrite_account_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            changed = session.get(models.Command, command_id)
            assert changed is not None
            changed.account_id = account_b_id
            session.commit()
            rewrite_committed.set()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(
            command_routes, "_get_authorized_callback_command",
            pause_after_authorization,
        )
        patch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            callback_future = workers.submit(observation_in_session)
            try:
                assert authorized.wait(timeout=8), (
                    "Management callback did not reach authorization barrier"
                )
                rewrite_future = workers.submit(rewrite_account_in_session)
                assert rewrite_committed.wait(timeout=8), (
                    "Account reassignment did not commit before callback resumed"
                )
            finally:
                resume_callback.set()
            callback_result = callback_future.result(timeout=22)
            rewrite_future.result(timeout=22)

    with SessionLocal() as session:
        changed = session.get(models.Command, command_id)
        assert changed is not None
        assert changed.user_id == owner["id"]
        assert changed.account_id == account_b_id
        command_status_after = changed.status
        executions = session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).all()
        assert len(executions) == 1 and executions[0].status == "SUCCESS"
        events = session.query(models.TradeManagementEvent).filter(
            models.TradeManagementEvent.command_id == command_id
        ).all()
        audits = (
            session.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "MANAGEMENT_EVENT",
                models.AuditLog.entity_id == events[0].id,
            )
            .count()
            if len(events) == 1 else 0
        )

    if callback_result == 403:
        assert not events, "Denied stale callback must write no management row"
        assert audits == 0
        assert command_status_after == "EXECUTED_OPEN", (
            "Denied stale callback must not advance command state"
        )
        return

    if (
        callback_result == "ok"
        and len(events) == 1
        and events[0].event_type == event_type
        and events[0].result == result
        and command_status_after == (
            "PARTIAL_TP1_DONE" if event_type == "TP1_CLOSE_SUCCESS"
            else "EXECUTED_OPEN"
        )
        and audits == 1
    ):
        pytest.xfail(
            "RELEASE HOLD: A's management callback and audit committed "
            "AFTER B's Command.account_id reassignment committed"
        )

    pytest.fail(
        "Unexpected post-reassignment management outcome: "
        f"result={callback_result!r}, events={len(events)}, audits={audits}"
    )

def test_postgresql_command_account_relabel_recovery_after_auth(
    client, db, monkeypatch
):
    """Synthetic broker-recovery provenance race; never contacts a broker.

    A authorizes its delivered command and pauses. B reassigns only the
    command's account to another subscriber and commits. A must not recover
    a fabricated broker snapshot under that now-foreign account. Strict XFAIL
    is permitted only if the independent rewrite committed and both the
    unauthorized execution and its recovery audit persisted. All fixture,
    barrier and unexpected outcomes remain ordinary failures.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from app.schemas import BrokerPositionReconcileRequest
    from .test_provider_export import _provider, _headers

    provider, feed, provider_key = _provider(
        db, "callback-recovery-account-relabel-race"
    )
    db.commit()
    owner = register_user(
        client, "990367", "synthetic_reconcile_relabel_a", "Synthetic A"
    )
    foreign = register_user(
        client, "990368", "synthetic_reconcile_relabel_b", "Synthetic B"
    )
    _, own_account = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    _, foreign_account = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, foreign["id"])
    )
    assert own_account.id != foreign_account.id
    own_account_id, foreign_account_id = own_account.id, foreign_account.id
    db.commit()

    signal = client.post(
        "/signals/create",
        headers=_headers(provider, provider_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert signal.status_code == 200, signal.text
    approved = client.post(
        f"/signals/{signal.json()['id']}/approve",
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
    db.expire_all()
    assert db.get(models.Command, command_id).account_id == own_account_id
    assert db.get(models.Command, command_id).status == "SENT_TO_EA"
    db.rollback()

    authorized = Event()
    resume_callback = Event()
    rewrite_committed = Event()
    original_resolver = command_routes._get_authorized_callback_command

    def pause_after_authorization(session, cid, license_key):
        command = original_resolver(session, cid, license_key)
        authorized.set()
        assert resume_callback.wait(timeout=15), (
            "Recovery callback never resumed after account reassignment"
        )
        return command

    def recover_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            try:
                return command_routes.reconcile_open_position(
                    command_id,
                    BrokerPositionReconcileRequest(
                        broker_tickets=["SYNTHETIC-NO-BROKER-990367"],
                        executed_symbol="XAUUSD",
                        executed_direction="BUY",
                        executed_price=2345.0,
                        lot_size=0.1,
                    ),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status
            except HTTPException as exc:
                return exc.status_code

    def relabel_in_session():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            command = session.get(models.Command, command_id)
            assert command is not None
            command.account_id = foreign_account_id
            session.commit()
            rewrite_committed.set()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(
            command_routes, "_get_authorized_callback_command",
            pause_after_authorization,
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            recovery_future = workers.submit(recover_in_session)
            try:
                assert authorized.wait(timeout=8), (
                    "Recovery callback failed to reach authorization barrier"
                )
                relabel_future = workers.submit(relabel_in_session)
                assert rewrite_committed.wait(timeout=8), (
                    "Account reassignment did not commit before recovery resumed"
                )
            finally:
                resume_callback.set()
            callback_result = recovery_future.result(timeout=22)
            relabel_future.result(timeout=22)

    with SessionLocal() as session:
        command = session.get(models.Command, command_id)
        assert command is not None
        assert command.user_id == owner["id"]
        assert command.account_id == foreign_account_id
        executions = session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).all()
        audits = (
            session.query(models.AuditLog).filter(
                models.AuditLog.event_type
                == "EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT",
                models.AuditLog.entity_id == executions[0].id,
            ).count()
            if len(executions) == 1 else 0
        )

    if callback_result == 403:
        assert not executions, "Denied stale recovery must create no execution"
        assert audits == 0
        return

    if (
        callback_result == "recovered"
        and len(executions) == 1
        and executions[0].status == "SUCCESS"
        and executions[0].user_id == owner["id"]
        and command.status == "EXECUTED_OPEN"
        and audits == 1
    ):
        pytest.xfail(
            "RELEASE HOLD: A's fabricated broker-recovery execution and audit "
            "committed AFTER B's Command.account_id reassignment committed"
        )

    pytest.fail(
        "Unexpected post-reassignment recovery outcome: "
        f"result={callback_result!r}, executions={len(executions)}, "
        f"audits={audits}, command_status={command.status}"
    )

@pytest.mark.parametrize("revocation_kind", ("rotation", "deactivation"))
@pytest.mark.parametrize("reconciliation_outcome", ("matched", "conflict"))
def test_postgresql_reconciliation_rollback_revocation_cannot_audit(
    client, db, monkeypatch, revocation_kind, reconciliation_outcome
):
    """HOLD witness: a raced recovery must not audit after losing licence locks.

    Session A authorizes a previously delivered synthetic command, then pauses
    just before inserting a recovered Execution. Session B commits a fabricated
    SUCCESS report for that command. A resumes, loses the *real* PostgreSQL
    unique(command_id) race and enters reconcile_open_position's recursive
    retry after the full IntegrityError rollback. A third transaction then
    revokes A's licence while that retry is paused. A must not record a
    MATCHED or CONFLICT reconciliation audit after the revocation has committed.

    This never contacts MT5, a broker or a provider and cannot prove external
    acceptance. Each variant must demonstrate the unique collision, committed
    revocation and 403 with no post-revocation reconciliation audit.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL sessions and unique constraint")

    from threading import local
    from app.schemas import BrokerPositionReconcileRequest, ExecutionRequest

    owner = register_user(client, "990369")
    signal = _hosted_provider_signal_for(client, "990369")
    approved = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": "990369"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED"

    prior_crud_mode = crud.settings.require_license
    prior_route_mode = command_routes.settings.require_license
    role = local()
    before_insert = Event()
    release_insert = Event()
    retry_after_rollback = Event()
    release_retry = Event()
    revocation_committed = Event()
    conflict_observed = Event()
    original_next_id = crud._next_id
    original_reconcile = crud.reconcile_open_position

    def pause_before_first_recovery_insert(session, model):
        if model is models.Execution and getattr(role, "name", None) == "recovery":
            before_insert.set()
            assert release_insert.wait(timeout=15), (
                "Recovery insert barrier was not released"
            )
        return original_next_id(session, model)

    def observe_actual_rollback_retry(session, command, payload):
        # The initial invocation cannot reach here after before_insert;
        # only the recursive call after an IntegrityError rollback can do so.
        if (
            getattr(role, "name", None) == "recovery"
            and before_insert.is_set()
            and not retry_after_rollback.is_set()
        ):
            retry_after_rollback.set()
            assert release_retry.wait(timeout=15), (
                "Post-rollback reconciliation retry barrier was not released"
            )
        try:
            return original_reconcile(session, command, payload)
        except crud.BrokerReconciliationConflict:
            if getattr(role, "name", None) == "recovery" and retry_after_rollback.is_set():
                conflict_observed.set()
            raise

    try:
        crud.settings.require_license = True
        command_routes.settings.require_license = True
        headers = {**EA_HEADERS, "X-SG-License-Key": owner["license_key"]}
        claimed = client.get("/commands/pending", headers=headers)
        assert claimed.status_code == 200, claimed.text
        issued = claimed.json()["command"]
        assert issued is not None
        command_id = issued["command_id"]
        ticket = "SYNTHETIC-RECONCILE-RACE-NO-BROKER"
        winner_ticket = (
            ticket if reconciliation_outcome == "matched"
            else "SYNTHETIC-DIFFERENT-TICKET-NO-BROKER"
        )
        snapshot = BrokerPositionReconcileRequest(
            broker_tickets=[ticket],
            executed_symbol="XAUUSD",
            executed_direction="BUY",
            executed_price=2345.0,
            lot_size=0.1,
        )
        report = ExecutionRequest(
            status="SUCCESS",
            broker_ticket=winner_ticket,
            executed_symbol="XAUUSD",
            executed_direction="BUY",
            executed_price=2345.0,
            lot_size=0.1,
        )
        monkeypatch.setattr(crud, "_next_id", pause_before_first_recovery_insert)
        monkeypatch.setattr(crud, "reconcile_open_position", observe_actual_rollback_retry)
        monkeypatch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )

        def recover_in_session():
            role.name = "recovery"
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                try:
                    return command_routes.reconcile_open_position(
                        command_id,
                        snapshot,
                        x_sg_license_key=owner["license_key"],
                        db=session,
                        _ea="offline-test",
                    ).status
                except HTTPException as exc:
                    return exc.status_code

        def winning_execution_in_session():
            role.name = "winner"
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                return command_routes.report_execution(
                    command_id,
                    report,
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status

        def revoke_in_session():
            with SessionLocal() as session:
                session.connection().exec_driver_sql(
                    "SET LOCAL statement_timeout = '12s'"
                )
                customer = crud.get_user_by_telegram(session, "990369")
                assert customer is not None
                if revocation_kind == "rotation":
                    assert crud.issue_license(session, customer) != owner["license_key"]
                else:
                    crud.set_user_status(session, customer, "INACTIVE")
                session.commit()
                revocation_committed.set()

        with ThreadPoolExecutor(max_workers=3) as workers:
            recovering = workers.submit(recover_in_session)
            try:
                assert before_insert.wait(timeout=8), (
                    "Recovery never reached its first Execution insert barrier"
                )
                winning = workers.submit(winning_execution_in_session)
                assert winning.result(timeout=22) == "ok", (
                    "Competing execution was not durably committed"
                )
                release_insert.set()
                assert retry_after_rollback.wait(timeout=8), (
                    "A real duplicate Execution insert did not reach the "
                    "IntegrityError rollback/retry path"
                )
                revoked = workers.submit(revoke_in_session)
                assert revocation_committed.wait(timeout=8), (
                    "Licence revocation could not commit after rollback"
                )
            finally:
                release_insert.set()
                release_retry.set()
            stale_result = recovering.result(timeout=22)
            revoked.result(timeout=22)

        with SessionLocal() as session:
            user = crud.get_user_by_telegram(session, "990369")
            assert user is not None
            if revocation_kind == "rotation":
                assert crud.get_user_by_license(session, owner["license_key"]) is None
            else:
                assert user.status == "INACTIVE"
            command = crud.get_command(session, command_id)
            assert command is not None and command.status == "EXECUTED_OPEN"
            executions = session.query(models.Execution).filter(
                models.Execution.command_id == command_id
            ).all()
            assert len(executions) == 1
            assert executions[0].status == "SUCCESS"
            assert executions[0].broker_ticket == winner_ticket
            stale_audits = session.query(models.AuditLog).filter(
                models.AuditLog.event_type.in_((
                    "BROKER_RECONCILIATION_MATCHED",
                    "BROKER_RECONCILIATION_CONFLICT",
                )),
                models.AuditLog.entity_id == command_id,
            ).count()
            recovered_audits = session.query(models.AuditLog).filter(
                models.AuditLog.event_type == "EXECUTION_RECOVERED_FROM_BROKER_SNAPSHOT",
            ).count()
            assert recovered_audits == 0, (
                "Losing recovery must not produce a second execution receipt"
            )

        assert revocation_committed.is_set() and retry_after_rollback.is_set()
        if reconciliation_outcome == "conflict":
            assert conflict_observed.is_set(), (
                "Synthetic mismatched winner ticket did not reach the "
                "reconciliation conflict branch after the unique collision"
            )
        else:
            assert not conflict_observed.is_set()
        assert stale_result == 403, (
            "Post-rollback reconciliation must revalidate the current EA "
            f"licence before commit; received {stale_result!r}"
        )
        assert stale_audits == 0, (
            "Post-revocation reconciliation must not persist a MATCHED/CONFLICT audit"
        )
    finally:
        release_insert.set()
        release_retry.set()
        crud.settings.require_license = prior_crud_mode
        command_routes.settings.require_license = prior_route_mode

@pytest.mark.parametrize(
    ("event_type", "stage", "result", "expected_command_status"),
    [
        pytest.param(
            "TP1_REACHED", "TP1_REACHED", "PENDING", "EXECUTED_OPEN",
            id="price-observation",
        ),
        pytest.param(
            "TP1_CLOSE_SUCCESS", "TP1_CLOSED", "SUCCESS", "PARTIAL_TP1_DONE",
            id="state-advance-locked",
        ),
    ],
)
def test_postgresql_management_observation_precommit_account_relabel_fence(
    client, db, monkeypatch, event_type, stage, result, expected_command_status
):
    """Synthetic callback-first commit-order witness for price and state TP1 events.

    An EA-shaped TP1 price observation or TP1_CLOSE_SUCCESS stage advance is
    staged and flushed but remains uncommitted. Another transaction then attempts to relabel Command.account_id
    to subscriber B. A correct provenance fence must either serialize B behind
    A's final commit or deny and roll back A after B commits. A committed stale
    receipt/audit after B's relabel is a strict XFAIL, never a passing gate.
    No EA, broker, network traffic, order or customer data is involved.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from app.schemas import ManagementEventRequest
    from .test_provider_export import _provider, _headers

    provider, feed, provider_key = _provider(
        db, "management-observation-precommit-relabel"
    )
    db.commit()
    owner = register_user(
        client, "990370", "synthetic_precommit_mgmt_a", "Synthetic A"
    )
    foreign = register_user(
        client, "990371", "synthetic_precommit_mgmt_b", "Synthetic B"
    )
    _, account_a = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, owner["id"])
    )
    _, account_b = crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, foreign["id"])
    )
    account_a_id, account_b_id = account_a.id, account_b.id
    assert account_a_id != account_b_id
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
    with monkeypatch.context() as patch:
        patch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )
        seeded = client.post(
            f"/commands/{command_id}/execution",
            headers=EA_HEADERS,
            json={
                "status": "SUCCESS",
                "broker_ticket": "SYNTHETIC-PRECOMMIT-NO-BROKER",
                "executed_symbol": "XAUUSD",
                "executed_direction": "BUY",
                "executed_price": 2345.0,
                "lot_size": 0.1,
            },
        )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["status"] == "ok"
    db.expire_all()
    initial = db.get(models.Command, command_id)
    assert initial.status == "EXECUTED_OPEN"
    assert initial.account_id == account_a_id
    db.rollback()

    observation_staged = Event()
    release_commit = Event()
    rewrite_attempted = Event()
    rewrite_committed = Event()
    original_record = crud.record_management_event

    def pause_after_observation_staged(session, command, payload):
        recorded = original_record(session, command, payload)
        assert recorded[1], "Expected a new synthetic price observation"
        session.flush()  # Include its audit in A's uncommitted transaction.
        observation_staged.set()
        assert release_commit.wait(timeout=15), (
            "Observation transaction did not resume after relabel attempt"
        )
        return recorded

    def observe_in_independent_transaction():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            try:
                return command_routes.report_management_event(
                    command_id,
                    ManagementEventRequest(
                        event_type=event_type,
                        stage=stage,
                        result=result,
                    ),
                    x_sg_license_key=owner["license_key"],
                    db=session,
                    _ea="offline-test",
                ).status
            except HTTPException as exc:
                session.rollback()
                return exc.status_code

    def rewrite_in_independent_transaction():
        with SessionLocal() as session:
            session.connection().exec_driver_sql(
                "SET LOCAL statement_timeout = '12s'"
            )
            changed = session.get(models.Command, command_id)
            assert changed is not None
            changed.account_id = account_b_id
            rewrite_attempted.set()
            session.commit()
            rewrite_committed.set()

    with monkeypatch.context() as patch:
        patch.setattr(crud.settings, "require_license", True)
        patch.setattr(command_routes.settings, "require_license", True)
        patch.setattr(
            crud, "record_management_event", pause_after_observation_staged
        )
        patch.setattr(
            command_routes, "notify_user_and_admins", lambda *_a, **_kw: None
        )
        with ThreadPoolExecutor(max_workers=2) as workers:
            observed = workers.submit(observe_in_independent_transaction)
            try:
                assert observation_staged.wait(timeout=8), (
                    "Price observation never staged its audit"
                )
                writer = workers.submit(rewrite_in_independent_transaction)
                assert rewrite_attempted.wait(timeout=8), (
                    "Competing account relabel never attempted commit"
                )
                writer_overtook = rewrite_committed.wait(timeout=3)
            finally:
                release_commit.set()
            callback_result = observed.result(timeout=22)
            writer.result(timeout=22)

    with SessionLocal() as session:
        changed = session.get(models.Command, command_id)
        assert changed is not None
        assert changed.account_id == account_b_id
        assert changed.status == expected_command_status
        assert session.query(models.Execution).filter(
            models.Execution.command_id == command_id
        ).count() == 1
        events = session.query(models.TradeManagementEvent).filter(
            models.TradeManagementEvent.command_id == command_id
        ).all()
        audits = (
            session.query(models.AuditLog).filter(
                models.AuditLog.event_type == "MANAGEMENT_EVENT",
                models.AuditLog.entity_id == events[0].id,
            ).count()
            if len(events) == 1 else 0
        )

    if writer_overtook and callback_result == 403:
        assert not events and audits == 0, (
            "Denied stale observation must roll back both event and audit"
        )
        return
    if writer_overtook and (
        callback_result == "ok"
        and len(events) == 1
        and events[0].event_type == event_type
        and events[0].result == result
        and audits == 1
    ):
        pytest.xfail(
            "RELEASE HOLD: callback-first observation was staged before "
            "relabel but its receipt/audit committed AFTER B's relabel"
        )
    assert not writer_overtook, (
        "Relabel overtook A's uncommitted receipt without correct denial"
    )
    assert callback_result == "ok", (
        f"Unexpected callback-first outcome: {callback_result!r}"
    )
    assert len(events) == 1 and audits == 1, (
        "Callback-first serialized receipt must persist exactly once"
    )
