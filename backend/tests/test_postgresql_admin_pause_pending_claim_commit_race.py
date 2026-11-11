"""Offline PostgreSQL witness: a global pause must serialize with EA command claim.

No real EA, MT5, broker, customer, Telegram, network API, or trading. This
test checks the committed-pause delivery serialization. Neither an
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


class _ClaimOvertookUncommittedPause(AssertionError):
    """EA command claim committed after a pause writer already locked the row."""


def test_paused_settings_writer_blocks_later_command_claim(client, db):
    """Inverse PostgreSQL race: pause writer owns row BEFORE EA claim starts.

    Unlike the earlier claim-first case, this holds the settings UPDATE
    uncommitted while the independent EA claim begins. The intended reader
    FOR SHARE must wait on the writer; once the writer commits 'true',
    the EA poll must see pause and leave the command PENDING. A strict
    XFAIL records only the current unsafe command delivery; scheduling
    errors, unexpected exceptions and execution side effects fail CI.
    Synthetic/local database sessions only; no EA or broker is contacted.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two independent PostgreSQL transactions")

    from time import monotonic, sleep
    from sqlalchemy import text as sql_text

    user = register_user(client, "990004")
    signal = create_signal(client, VALID)
    response = client.post(
        f"/signals/{signal['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "APPROVED"
    command_id = response.json()["command_id"]

    claim_query_attempted = Event()
    claim_pids: list[int] = []

    def claim_after_pause_writer():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

            def observe_select(_conn, _cursor, statement, _params, _ctx, _many):
                lowered = statement.lstrip().lower()
                if lowered.startswith("select") and (
                    "settings" in lowered or "commands" in lowered
                ):
                    claim_query_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_select)
            command = crud.get_pending_command_for_user(session, user["id"])
            session.commit()
            return command.id if command is not None else None

    with SessionLocal() as pause_writer:
        pause_conn = pause_writer.connection()
        pause_conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
        pause_pid = pause_conn.exec_driver_sql(
            "SELECT pg_backend_pid()"
        ).scalar_one()
        current = pause_writer.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert current is not None and current.value == "false"
        # This real UPDATE holds a PostgreSQL row lock before the EA reader
        # starts. Do not add an audit until after claim coordination:
        # audit advisory locks would mask the settings-row race being tested.
        crud.set_setting(pause_writer, "admin_paused", "true")

        with ThreadPoolExecutor(max_workers=1) as workers:
            claim_future = workers.submit(claim_after_pause_writer)
            blocked_on_pause = False
            try:
                assert claim_query_attempted.wait(timeout=8), (
                    "EA claim never attempted its first settings/commands SELECT"
                )
                with SessionLocal() as observer:
                    deadline = monotonic() + 2.0
                    while monotonic() < deadline:
                        observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                        blockers = observer.scalar(
                            sql_text("SELECT pg_blocking_pids(:claim_pid)"),
                            {"claim_pid": claim_pids[0]},
                        )
                        if pause_pid in blockers:
                            blocked_on_pause = True
                            break
                        if claim_future.done():
                            break
                        sleep(0.05)
                early_delivery = claim_future.done()
                if not early_delivery:
                    assert blocked_on_pause, (
                        "EA claim was not observed waiting for the settings "
                        "row locked by the earlier pause writer"
                    )
            finally:
                # Commit/release the pause row even when an assertion fails.
                pause_writer.commit()
            claimed_id = claim_future.result(timeout=15)

    with SessionLocal() as check:
        pause_row = check.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        command = check.get(models.Command, command_id)
        assert pause_row is not None and pause_row.value == "true"
        assert command is not None
        sent_audits = check.query(models.AuditLog).filter(
            models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
            models.AuditLog.entity_id == command_id,
        ).count()
        executions = check.query(models.Execution).count()

    assert executions == 0  # Never conceal this failure inside an XFAIL.
    if early_delivery and claimed_id == command_id:
        assert command.status == "SENT_TO_EA"
        assert sent_audits == 1
        raise _ClaimOvertookUncommittedPause(
            "EA claim delivered while earlier admin pause UPDATE held its "
            "settings-row lock; pause committed afterward"
        )

    assert blocked_on_pause
    assert claimed_id is None
    assert command.status == "PENDING"
    assert sent_audits == 0
