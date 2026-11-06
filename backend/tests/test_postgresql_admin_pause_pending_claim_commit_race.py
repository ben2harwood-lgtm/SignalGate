"""Offline PostgreSQL witness: a global pause must serialize with EA command claim.

No real EA, MT5, broker, customer, Telegram, network API, or trading. This
strict-XFAIL test describes an unimplemented release safeguard. Neither an
expected failure nor SQLite's skip is security or external acceptance.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import event, select

from app import crud, models
from app.database import SessionLocal

from .conftest import ADMIN_HEADERS, create_signal, register_user


VALID = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


class _PauseCommittedBeforeClaim(AssertionError):
    """A global admin pause committed ahead of the older held claim."""


@pytest.mark.xfail(
    strict=True,
    raises=_PauseCommittedBeforeClaim,
    reason=(
        "RELEASE HOLD: a committed global pause can overtake an in-flight "
        "EA command claim on PostgreSQL; shared-row locking is unproven"
    ),
)
def test_committed_admin_pause_cannot_overtake_command_claim_postgresql(
    client, db, monkeypatch
):
    """Coordinate real independent DB transactions on fabricated demo data.

    The claim worker reaches COMMAND_SENT_TO_EA audit before its transaction
    commits. While that commit is held, the pause worker attempts the actual
    settings UPDATE and commit. A safe fix must serialize them: an earlier
    claim may commit before the later pause, but the pause cannot *commit*
    first and still permit that older in-flight claim to commit afterwards.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    user = register_user(client, "990002")
    signal = create_signal(client, VALID)
    decision = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert decision.status_code == 200
    assert decision.json()["result"] == "APPROVED"
    command_id = decision.json()["command_id"]

    claim_staged = Event()
    release_claim = Event()
    pause_update_attempted = Event()
    pause_committed = Event()
    original_add_audit = crud.add_audit

    def gate_claim_audit(session, event_type, entity_type=None, entity_id=None, payload=None):
        if event_type == "COMMAND_SENT_TO_EA":
            claim_staged.set()
            assert release_claim.wait(timeout=15), "Held claim was never released"
        return original_add_audit(
            session, event_type, entity_type, entity_id, payload
        )

    monkeypatch.setattr(crud, "add_audit", gate_claim_audit)

    def claim_pending():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            command = crud.get_pending_command_for_user(session, user["id"])
            assert command is not None
            assert command.id == command_id
            assert command.status == "SENT_TO_EA"
            session.commit()
            return command.id

    def commit_admin_pause():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_update(_conn, _cursor, sql, _params, _ctx, _many):
                if sql.lstrip().lower().startswith("update settings set"):
                    pause_update_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_update)
            crud.set_setting(session, "admin_paused", "true")
            crud.add_audit(session, "ADMIN_PAUSE", "settings", "admin_paused")
            session.commit()
            pause_committed.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        claim_future = workers.submit(claim_pending)
        try:
            assert claim_staged.wait(timeout=8), "Command did not reach pre-commit audit gate"
            pause_future = workers.submit(commit_admin_pause)
            assert pause_update_attempted.wait(timeout=8), (
                "Concurrent admin pause never attempted its settings UPDATE"
            )
            # Under the unfixed implementation, pause commits while the
            # in-flight claim is intentionally held. Under a shared-row lock,
            # pause waits until the earlier claim commits.
            # Capture the observed commit while the claim is STILL held.
            # Reading release_claim in the pause worker after its commit can
            # miss a pause that overtook the claim just after we release it.
            pause_overtook_held_claim = pause_committed.wait(timeout=2.5)
        finally:
            release_claim.set()
        assert claim_future.result(timeout=22) == command_id
        pause_future.result(timeout=22)

    # Prove both transactions committed, with exactly one claim, one pause,
    # and no fabricated execution. Do not count a deadlock/timeout as proof.
    with SessionLocal() as session:
        paused = session.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        command = session.get(models.Command, command_id)
        assert paused is not None and paused.value == "true"
        assert command is not None and command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert session.scalar(
            select(models.Approval).where(models.Approval.id == command.approval_id)
        ) is not None
        assert session.query(models.Execution).count() == 0
        assert (
            session.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
            == 1
        )
        assert (
            session.query(models.AuditLog)
            .filter(models.AuditLog.event_type == "ADMIN_PAUSE")
            .count()
            == 1
        )

    if pause_overtook_held_claim:
        raise _PauseCommittedBeforeClaim(
            "Admin pause committed before the held COMMAND_SENT_TO_EA claim "
            "transaction, but that old claim committed afterwards"
        )
