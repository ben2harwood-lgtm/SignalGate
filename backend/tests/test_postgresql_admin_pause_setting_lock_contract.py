"""Synthetic PostgreSQL lock-mode contract for the global admin pause row.

This is NOT a test of application pause enforcement, broker execution, or
real trading. It demonstrates which PostgreSQL reader lock can serialize
a pause-setting UPDATE with a pending-command claim transaction.
No external services, broker, Telegram, identities, or paid tools are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import event, select, text as sql_text

from app import crud, models
from app.database import SessionLocal


@pytest.mark.parametrize(
    ("lock_mode", "pause_must_wait"),
    (("share", True), ("key_share", False)),
)
def test_global_admin_pause_update_conflicts_with_correct_lock(
    client, db, lock_mode, pause_must_wait
):
    """Prove FOR SHARE blocks the real settings.value UPDATE; KEY SHARE does not.

    Both workers use independent PostgreSQL connections and transactions. The
    writer is observed attempting the UPDATE before checking PostgreSQL's
    blocking graph, to avoid confusing scheduler delay with safety.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires two real independent PostgreSQL transactions")

    with SessionLocal() as setup:
        row = setup.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert row is not None and row.value == "false"

    reader_locked = Event()
    release_reader = Event()
    writer_update_attempted = Event()
    writer_committed = Event()
    reader_pids: list[int] = []
    writer_pids: list[int] = []

    def lock_reader():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            reader_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )
            row = session.scalar(
                select(models.Setting)
                .where(models.Setting.key == "admin_paused")
                .with_for_update(
                    read=True, key_share=(lock_mode == "key_share")
                )
            )
            assert row is not None and row.value == "false"
            reader_locked.set()
            try:
                assert release_reader.wait(timeout=15), (
                    "Coordinator never released settings-row reader"
                )
            finally:
                session.commit()

    def commit_pause():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            writer_pids.append(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

            def observed_update(_conn, _cursor, statement, _params, _ctx, _many):
                if statement.lstrip().lower().startswith("update settings set"):
                    writer_update_attempted.set()

            event.listen(conn, "before_cursor_execute", observed_update)
            # Calls the real settings writer, but does NOT call the HTTP admin
            # endpoint or mutate any command/execution state.
            crud.set_setting(session, "admin_paused", "true")
            session.commit()
            committed_while_reader_held = not release_reader.is_set()
            writer_committed.set()
            return committed_while_reader_held

    with ThreadPoolExecutor(max_workers=2) as workers:
        reader_future = workers.submit(lock_reader)
        try:
            assert reader_locked.wait(timeout=8), "Reader did not take row lock"
            writer_future = workers.submit(commit_pause)
            assert writer_update_attempted.wait(timeout=8), (
                "Independent pause writer never attempted the settings UPDATE"
            )
            if pause_must_wait:
                with SessionLocal() as observer:
                    deadline = monotonic() + 4.0
                    while monotonic() < deadline:
                        blockers = observer.scalar(
                            sql_text("SELECT pg_blocking_pids(:writer_pid)"),
                            {"writer_pid": writer_pids[0]},
                        )
                        if reader_pids[0] in blockers:
                            break
                        sleep(0.05)
                    else:
                        pytest.fail(
                            "FOR SHARE did not block the settings UPDATE "
                            "on the observed PostgreSQL reader backend"
                        )
                assert not writer_committed.is_set(), (
                    "Admin pause committed before FOR SHARE reader released"
                )
            else:
                assert writer_committed.wait(timeout=8), (
                    "FOR KEY SHARE unexpectedly blocked a non-key pause UPDATE"
                )
        finally:
            release_reader.set()

        reader_future.result(timeout=18)
        committed_early = writer_future.result(timeout=18)

    assert committed_early is (not pause_must_wait)
    with SessionLocal() as check:
        row = check.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert row is not None and row.value == "true"
        assert check.query(models.Command).count() == 0
        assert check.query(models.Execution).count() == 0
