"""Offline PostgreSQL witness for an EA callback versus customer licence rotation.

This is a strict release HOLD witness, not authorization-policy acceptance.
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


class _CallbackCommittedAfterLicenceRevoked(AssertionError):
    """Old EA authorization survived a completed licence rotation."""


@pytest.mark.xfail(
    strict=True,
    raises=_CallbackCommittedAfterLicenceRevoked,
    reason=(
        "RELEASE HOLD: establish whether a callback authorized before licence "
        "rotation may commit a new receipt after revocation committed"
    ),
)
def test_postgresql_callback_receipt_cannot_overtake_committed_licence_rotation(
    client, db, monkeypatch
):
    """Stage the actual callback route between its authorization and receipt.

    Transaction A authorizes a fabricated claimed command with the old key
    then stops BEFORE recording the acknowledgement. Transaction B rotates
    that customer's licence and commits. Only then A resumes. An enforceable
    strict-revocation policy should either block B until A finishes, or deny
    A's new audit after B commits; it must not accept an old-key receipt after
    a completed rotation. An XFAIL records the present gap, not a passed gate.

    Distinct PostgreSQL sessions and a pre-commit barrier make the ordering
    observable, without creating a real execution or invoking a broker.
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

        # A transaction that took the earlier authorization may finish BEFORE
        # revocation commits. That ordering is not this test's security claim.
        assert acknowledgements in (0, 1)
        if rotation_overtook_callback and reply.status == "received" and acknowledgements:
            raise _CallbackCommittedAfterLicenceRevoked(
                "Old-key acknowledgement committed after the independently "
                "observed licence-rotation commit"
            )
    finally:
        release_callback.set()
        crud.settings.require_license = former_crud_mode
        command_routes.settings.require_license = former_route_mode
