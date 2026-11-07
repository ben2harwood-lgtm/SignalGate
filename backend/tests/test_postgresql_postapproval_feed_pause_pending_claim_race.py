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
