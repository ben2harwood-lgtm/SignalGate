"""Offline PostgreSQL witness: a committed pause must not be overtaken by signal commit.

Two real database transactions are orchestrated without a broker, Telegram,
external provider, or model. This is a strict XFAIL for the existing release
HOLD, not evidence that pause/creation serialization already works.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import event

from app import crud, models
from app.database import SessionLocal

from .test_provider_sources import EUR_BUY, _provider


class _CommittedPauseOvertaken(AssertionError):
    """A pause committed while signal creation was still held before commit."""


@pytest.mark.parametrize("paused_scope_name", ("provider", "feed"))
@pytest.mark.xfail(
    strict=True,
    raises=_CommittedPauseOvertaken,
    reason=(
        "RELEASE HOLD: signal creation does not serialize provider/feed pause "
        "against a concurrent PostgreSQL commit; independent lock review needed"
    ),
)
def test_committed_pause_cannot_be_overtaken_by_signal_commit_postgresql(
    db, monkeypatch, paused_scope_name
):
    """RED-before: ensure one of the two conflicting commits goes first.

    The signal worker stops after inserting its Signal but before its audit
    and commit. A separate PostgreSQL session then attempts to pause the
    ACTIVE provider/feed. If it commits while the signal is intentionally
    held, later committing that stale signal is a concrete policy violation.
    A future shared-lock repair must keep the pause blocked until the earlier
    signal transaction finishes, not rely on stale ORM identity-map state.

    The second worker's actual UPDATE is observed before releasing the first
    worker. Both transactions have bounded database and Python waits.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL transactions")

    provider, feed, _key = _provider(
        db, f"pause-signal-commit-{paused_scope_name}"
    )
    model = models.Provider if paused_scope_name == "provider" else models.Feed
    target_id = provider.id if paused_scope_name == "provider" else feed.id
    provider_id, feed_id = provider.id, feed.id
    source_message_id = f"offline-pg-pause-{paused_scope_name}"

    signal_staged = Event()
    allow_signal_commit = Event()
    pause_update_attempted = Event()
    pause_committed = Event()
    original_add_audit = crud.add_audit

    def gate_signal_audit(session, event_type, entity_type, entity_id, payload):
        if event_type == "SIGNAL_CREATED":
            signal_staged.set()
            assert allow_signal_commit.wait(timeout=18), (
                "Signal transaction was not released by the concurrency test"
            )
        return original_add_audit(
            session, event_type, entity_type, entity_id, payload
        )

    monkeypatch.setattr(crud, "add_audit", gate_signal_audit)

    def create_from_unpaused_source():
        with SessionLocal() as session:
            connection = session.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            signal, newly_created = crud.create_signal_with_freshness(
                session,
                raw_text=EUR_BUY,
                source="OFFLINE_PAUSE_SERIALIZATION",
                source_message_id=source_message_id,
                provider_id=provider_id,
                feed_id=feed_id,
            )
            assert newly_created is True
            assert signal.provider_id == provider_id
            assert signal.feed_id == feed_id
            signal_id = signal.id
            session.commit()
            return signal_id

    def pause_with_independent_commit():
        with SessionLocal() as writer:
            connection = writer.connection()
            connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            def observe_update(_conn, _cursor, statement, _params, _ctx, _many):
                if statement.lstrip().lower().startswith(
                    f"update {model.__tablename__} set"
                ):
                    pause_update_attempted.set()

            event.listen(connection, "before_cursor_execute", observe_update)
            target = writer.get(model, target_id)
            assert target is not None
            assert target.status == "ACTIVE"
            assert target.paused is False
            target.paused = True
            writer.commit()
            # This can only be true if the pause actually committed while
            # the first transaction was held at its pre-commit barrier.
            overtook = not allow_signal_commit.is_set()
            pause_committed.set()
            return overtook

    with ThreadPoolExecutor(max_workers=2) as workers:
        signal_future = workers.submit(create_from_unpaused_source)
        try:
            assert signal_staged.wait(timeout=8), (
                "Signal never reached the post-insert, pre-commit gate"
            )
            pause_future = workers.submit(pause_with_independent_commit)
            assert pause_update_attempted.wait(timeout=8), (
                "Competing pause never attempted its PostgreSQL UPDATE"
            )
            # A missing provider/feed shared lock permits the pause to
            # commit during this bounded hold. If properly serialized, it
            # waits until the signal's transaction has committed.
            pause_committed.wait(timeout=1.5)
        finally:
            allow_signal_commit.set()
        signal_id = signal_future.result(timeout=22)
        overtook = pause_future.result(timeout=22)

    # These checks ensure that the witness used real committed DB rows and
    # didn't report a race just because of a thread/fixture scheduling error.
    with SessionLocal() as check:
        paused = check.get(model, target_id)
        assert paused is not None
        assert paused.status == "ACTIVE" and paused.paused is True
        signal = check.get(models.Signal, signal_id)
        assert signal is not None
        assert signal.source_message_id == source_message_id
        assert signal.provider_id == provider_id
        assert signal.feed_id == feed_id
        assert (
            check.query(models.AuditLog)
            .filter(
                models.AuditLog.event_type == "SIGNAL_CREATED",
                models.AuditLog.entity_id == signal_id,
            )
            .count()
            == 1
        )
        assert check.query(models.Command).count() == 0
        assert check.query(models.Execution).count() == 0

    if overtook:
        raise _CommittedPauseOvertaken(
            f"{paused_scope_name} pause committed while SIGNAL_CREATED was "
            "held before commit; the stale signal then committed afterwards"
        )
