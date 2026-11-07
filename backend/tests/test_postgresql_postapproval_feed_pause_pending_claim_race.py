"""RELEASE HOLD: a committed feed pause cannot overtake an in-flight EA claim.

PostgreSQL-only two-session witness with fabricated users and providers.
This uses the database CRUD path, not a real EA, MT5, Telegram, broker or order.
The strict XFAIL is evidence of an UNFIXED command-delivery race, not a guard
that has passed and not an external or production acceptance receipt.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import event

from app import crud, models
from app.database import SessionLocal

from .conftest import register_user
from .test_provider_export import VALID, _headers, _provider


class _FeedPauseCommittedAheadOfHeldClaim(AssertionError):
    """A paused feed committed before an older held command claim committed."""


@pytest.mark.xfail(
    strict=True,
    raises=_FeedPauseCommittedAheadOfHeldClaim,
    reason=(
        "RELEASE HOLD: pending EA claim does not serialize against a "
        "concurrently committed provider-feed pause on PostgreSQL"
    ),
)
def test_feed_pause_cannot_overtake_pending_command_claim(client, db, monkeypatch):
    """Stage a real pending claim, then try to commit the feed pause ahead of it.

    The claim's SENT audit is held before its transaction commits. The second
    transaction updates the actual feed row. Under a safe shared-row locking
    repair, that UPDATE must wait until the older claim commits. A pause
    committed first must never be followed by that older claim's delivery.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two distinct PostgreSQL database transactions")

    provider, feed, raw_key = _provider(db, "pg-pending-feed-pause-race")
    user = register_user(client, "990093", "synthetic_feed_race", "Synthetic")
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()
    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    assert created.json()["parser_status"] == "VALID"
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED", approved.text
    command_id = approved.json()["command_id"]
    feed_id = feed.id
    db.rollback()  # Do not let fixture-session reads hold the test race open.

    claim_staged = Event()
    release_claim = Event()
    pause_update_attempted = Event()
    pause_committed = Event()
    original_add_audit = crud.add_audit

    def hold_sent_audit(session, event_type, entity_type=None, entity_id=None, payload=None):
        if event_type == "COMMAND_SENT_TO_EA" and entity_id == command_id:
            claim_staged.set()
            assert release_claim.wait(timeout=15), "Staged claim never released"
        return original_add_audit(session, event_type, entity_type, entity_id, payload)

    monkeypatch.setattr(crud, "add_audit", hold_sent_audit)

    def claim_command():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claimed = crud.get_pending_command_for_user(session, user["id"])
            assert claimed is not None and claimed.id == command_id
            assert claimed.status == "SENT_TO_EA"
            session.commit()
            return claimed.id

    def pause_feed():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_update(_conn, _cursor, sql, _params, _ctx, _many):
                if sql.lstrip().lower().startswith("update feeds set"):
                    pause_update_attempted.set()

            event.listen(conn, "before_cursor_execute", observe_update)
            persisted_feed = session.get(models.Feed, feed_id)
            assert persisted_feed is not None and persisted_feed.paused is False
            persisted_feed.paused = True
            session.flush()  # Actual UPDATE must try to obtain the feed-row lock.
            session.commit()
            pause_committed.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        claim_future = workers.submit(claim_command)
        try:
            assert claim_staged.wait(timeout=8), "Claim did not reach audit gate"
            pause_future = workers.submit(pause_feed)
            assert pause_update_attempted.wait(timeout=8), (
                "Concurrent feed pause never attempted its row UPDATE"
            )
            # Observe the pause commit *while* the original claim is held.
            # Looking after releasing the claim would not establish order.
            pause_overtook_claim = pause_committed.wait(timeout=2.0)
        finally:
            release_claim.set()
        assert claim_future.result(timeout=22) == command_id
        pause_future.result(timeout=22)

    with SessionLocal() as verify:
        persisted_feed = verify.get(models.Feed, feed_id)
        command = verify.get(models.Command, command_id)
        assert persisted_feed is not None and persisted_feed.paused is True
        assert command is not None and command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert verify.query(models.Execution).count() == 0
        sent_audits = (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        )
        assert sent_audits == 1

    if pause_overtook_claim:
        raise _FeedPauseCommittedAheadOfHeldClaim(
            "Feed pause committed while the approved command's SENT audit "
            "was held, yet that older command claim committed afterward"
        )


class _PauseWriterFirstUnsafeDelivery(AssertionError):
    """EA claim crossed an uncommitted feed pause and delivered the command."""


@pytest.mark.xfail(
    strict=True,
    raises=_PauseWriterFirstUnsafeDelivery,
    reason=(
        "RELEASE HOLD: EA claim can deliver while another PostgreSQL "
        "transaction has already updated the feed row to paused"
    ),
)
def test_feed_pause_writer_first_blocks_or_refuses_pending_claim(client, db):
    """Hold the feed pause UPDATE first; an EA claim may not overtake it.

    The first connection has flushed paused=True but has not committed, and
    therefore owns the PostgreSQL feed row lock. The second connection polls
    an already-YES-approved PENDING command. A safe claim either refuses
    immediately or waits on that feed lock, observes the committed pause and
    returns None. A delivered command is a strict expected-failure witness,
    never a passing safety control. No actual broker or EA is used.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL writer and claimer sessions")

    provider, feed, raw_key = _provider(db, "pg-feed-pause-writer-first")
    user = register_user(client, "990094", "synthetic_writer_first", "Synthetic")
    crud.subscribe_user_to_feed(
        db, provider, feed, db.get(models.User, user["id"])
    )
    db.commit()
    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": feed.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    assert created.json()["parser_status"] == "VALID"
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": user["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED", approved.text
    command_id = approved.json()["command_id"]
    feed_id = feed.id
    user_id = user["id"]
    db.rollback()

    with SessionLocal() as verify_before:
        assert verify_before.get(models.Command, command_id).status == "PENDING"
        assert verify_before.get(models.Feed, feed_id).paused is False

    pause_flushed = Event()
    release_pause = Event()
    claim_started = Event()
    claim_finished = Event()
    pause_pid = []
    claim_pid = []

    def hold_paused_feed_row():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            pause_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            persisted_feed = session.get(models.Feed, feed_id)
            assert persisted_feed is not None and persisted_feed.paused is False
            persisted_feed.paused = True
            session.flush()  # Row UPDATE and lock occur before the EA poll.
            pause_flushed.set()
            assert release_pause.wait(timeout=15), "Pause writer was not released"
            session.commit()
            return True

    def claim_while_pause_uncommitted():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            claim_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            claim_started.set()
            try:
                claimed = crud.get_pending_command_for_user(session, user_id)
                claimed_id = claimed.id if claimed is not None else None
                session.commit()
                return claimed_id
            finally:
                claim_finished.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        pause_future = workers.submit(hold_paused_feed_row)
        try:
            assert pause_flushed.wait(timeout=8), "Pause UPDATE was never flushed"
            claim_future = workers.submit(claim_while_pause_uncommitted)
            assert claim_started.wait(timeout=8), "EA claim did not start"

            # If the claimer does not finish immediately, prove it is waiting
            # on this exact feed writer, not an unrelated deadlock/test stall.
            finished_before_pause_commit = claim_finished.wait(timeout=2.0)
            if not finished_before_pause_commit:
                from time import sleep

                blocker_seen = False
                for _ in range(25):
                    with SessionLocal() as observer:
                        blockers = observer.connection().exec_driver_sql(
                            "SELECT pg_blocking_pids(%s)", (claim_pid[0],)
                        ).scalar_one()
                    if pause_pid[0] in blockers:
                        blocker_seen = True
                        break
                    if claim_finished.is_set():
                        break
                    sleep(0.05)
                assert blocker_seen, (
                    "Claim did not finish but PostgreSQL does not show the "
                    "paused feed writer as a blocker"
                )
        finally:
            release_pause.set()
        assert pause_future.result(timeout=20) is True
        claimed_id = claim_future.result(timeout=20)

    with SessionLocal() as verify:
        persisted_feed = verify.get(models.Feed, feed_id)
        persisted_command = verify.get(models.Command, command_id)
        assert persisted_feed is not None and persisted_feed.paused is True
        assert persisted_command is not None
        sent_audits = (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        )
        assert verify.query(models.Execution).count() == 0

        if claimed_id is not None:
            # Raise the narrow XFAIL only after positive proof of the unsafe
            # claimed state and persisted audit, never for fixture errors.
            assert claimed_id == command_id
            assert persisted_command.status == "SENT_TO_EA"
            assert persisted_command.sent_to_ea_at is not None
            assert sent_audits == 1
            raise _PauseWriterFirstUnsafeDelivery(
                "EA delivered an approved command while the same feed's "
                "pause UPDATE was already flushed and held uncommitted; "
                f"claim completed before pause commit: {finished_before_pause_commit}"
            )

        assert persisted_command.status == "PENDING"
        assert persisted_command.sent_to_ea_at is None
        assert sent_audits == 0


def test_locked_feed_pause_allows_same_provider_sibling_claim(client, db):
    """An unrelated active sibling feed stays pollable during a held feed pause.

    This is a normal PASS liveness/isolation control, not a test of whether the
    paused feed's own pending commands are safe. Two real PostgreSQL sessions
    are used with synthetic data only; no EA or broker is contacted. A repair
    that globally locks a provider's every feed while pausing just one feed
    must fail this control rather than silently halt authorised sibling work.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL pause and claim sessions")

    provider, feed_a, raw_key = _provider(db, "pg-feed-sibling-liveness")
    feed_b = crud.create_feed(
        db, provider, "Sibling active feed", "pg-feed-sibling-source"
    )
    # create_feed appends an audit and holds PostgreSQL's transaction-scoped
    # audit-chain advisory lock. Release it before register_user opens an HTTP
    # transaction that must append its own audit; otherwise this test deadlocks
    # against its own fixture session before either race worker starts.
    db.commit()
    user_b = register_user(
        client, "990095", "synthetic_sibling_liveness", "Synthetic B"
    )
    crud.subscribe_user_to_feed(
        db, provider, feed_b, db.get(models.User, user_b["id"])
    )
    db.commit()
    assert feed_a.id != feed_b.id
    assert feed_a.provider_id == feed_b.provider_id == provider.id
    created = client.post(
        "/signals/create",
        headers=_headers(provider, raw_key),
        json={"feed_id": feed_b.id, "raw_text": VALID},
    )
    assert created.status_code == 200, created.text
    assert created.json()["parser_status"] == "VALID"
    approved = client.post(
        f"/signals/{created.json()['id']}/approve",
        json={"telegram_user_id": user_b["telegram_user_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"] == "APPROVED", approved.text
    command_id = approved.json()["command_id"]
    feed_a_id, feed_b_id, user_b_id = feed_a.id, feed_b.id, user_b["id"]
    db.rollback()

    with SessionLocal() as verify_before:
        assert verify_before.get(models.Command, command_id).status == "PENDING"
        assert verify_before.get(models.Feed, feed_a_id).paused is False
        assert verify_before.get(models.Feed, feed_b_id).paused is False

    pause_flushed = Event()
    release_pause = Event()
    pause_pid = []
    claim_pid = []

    def hold_feed_a_pause():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            pause_pid.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            feed = session.get(models.Feed, feed_a_id)
            assert feed is not None and feed.paused is False
            feed.paused = True
            session.flush()  # Own feed A's UPDATE/row lock until explicitly released.
            pause_flushed.set()
            assert release_pause.wait(timeout=15), "Feed A pause not released"
            session.commit()

    def claim_active_sibling_feed():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
            claim_pid.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            claimed = crud.get_pending_command_for_user(session, user_b_id)
            claimed_id = claimed.id if claimed is not None else None
            session.commit()
            return claimed_id

    with ThreadPoolExecutor(max_workers=2) as workers:
        pause_future = workers.submit(hold_feed_a_pause)
        try:
            assert pause_flushed.wait(timeout=8), "Feed A did not flush pause"
            claim_future = workers.submit(claim_active_sibling_feed)
            # MUST finish before releasing A's row lock: otherwise a global
            # provider lock or wrong-feed lock could look like a normal pass.
            sibling_command = claim_future.result(timeout=4)
            assert sibling_command == command_id
        finally:
            release_pause.set()
        pause_future.result(timeout=20)

    assert len(pause_pid) == len(claim_pid) == 1
    assert pause_pid[0] != claim_pid[0], "Not independent PostgreSQL sessions"
    with SessionLocal() as verify:
        assert verify.get(models.Feed, feed_a_id).paused is True
        assert verify.get(models.Feed, feed_b_id).paused is False
        command = verify.get(models.Command, command_id)
        assert command is not None and command.feed_id == feed_b_id
        assert command.status == "SENT_TO_EA"
        assert command.sent_to_ea_at is not None
        assert (
            verify.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "COMMAND_SENT_TO_EA",
                models.AuditLog.entity_id == command_id,
            )
            .count()
        ) == 1
        assert verify.query(models.Execution).count() == 0
