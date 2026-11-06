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


@pytest.mark.parametrize(
    ("action", "initial_value", "final_value", "audit_event"),
    (
        ("pause", "false", "true", "ADMIN_PAUSE"),
        ("resume", "true", "false", "ADMIN_RESUME"),
    ),
)
def test_real_admin_pause_endpoint_waits_for_shared_settings_lock(
    client, db, action, initial_value, final_value, audit_event
):
    """Both authenticated HTTP pause and resume must serialize with FOR SHARE.

    This checks the actual /admin/pause and /admin/resume transactions, not only
    crud.set_setting. It does NOT assert that EA polling already acquires
    the required lock; the negative poll/claim XFAILs remain release holds.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires independent PostgreSQL HTTP and reader sessions")

    if action == "resume":
        # Start the resume case from a trusted paused row. Setup alone
        # does not count as an HTTP action or external acceptance evidence.
        with SessionLocal() as setup:
            row = setup.scalar(
                select(models.Setting).where(models.Setting.key == "admin_paused")
            )
            assert row is not None and row.value == "false"
            crud.set_setting(setup, "admin_paused", "true")
            setup.commit()

    # TestClient uses a separate app DB session; this reader owns the
    # settings-row lock until the coordinated release below.
    with SessionLocal() as reader:
        conn = reader.connection()
        conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
        conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
        reader_pid = conn.exec_driver_sql(
            "SELECT pg_backend_pid()"
        ).scalar_one()
        pause_setting = reader.scalar(
            select(models.Setting)
            .where(models.Setting.key == "admin_paused")
            .with_for_update(read=True)
        )
        assert pause_setting is not None and pause_setting.value == initial_value

        # The real endpoint must block at UPDATE settings (not merely be
        # slow to schedule). PostgreSQL identifies the exact blocker PID.
        from .conftest import ADMIN_HEADERS

        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                client.post, f"/admin/{action}", headers=ADMIN_HEADERS
            )
            try:
                with SessionLocal() as observer:
                    deadline = monotonic() + 5.0
                    while monotonic() < deadline:
                        # pg_stat_activity query snapshots can be cached for a
                        # transaction. Refresh each probe so a writer that
                        # starts after the first sample remains observable.
                        observer.execute(sql_text("SELECT pg_stat_clear_snapshot()"))
                        waiting = observer.execute(
                            sql_text(
                                "SELECT pid, query, pg_blocking_pids(pid) "
                                "FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND pid <> pg_backend_pid()"
                            )
                        ).all()
                        # The SQL text need not *start* with UPDATE: drivers
                        # may include statement prefixes. Keep the actual
                        # blocked-settings-writer assertion, not a timing guess.
                        blocked = [
                            (pid, query)
                            for pid, query, blockers in waiting
                            if reader_pid in blockers
                        ]
                        if any(
                            "update" in (query or "").lower()
                            and "settings" in (query or "").lower()
                            for _, query in blocked
                        ):
                            break
                        sleep(0.05)
                    else:
                        pytest.fail(
                            f"Real /admin/{action} UPDATE was not observed blocked "
                            "by the FOR SHARE settings reader; "
                            f"blocked queries: {[(pid, str(query)[:160]) for pid, query in blocked]}"
                        )

                    assert not future.done(), (
                        f"Admin {action} returned before the settings lock was released"
                    )
                    still_unchanged = observer.scalar(
                        select(models.Setting).where(
                            models.Setting.key == "admin_paused"
                        )
                    )
                    assert still_unchanged is not None
                    assert still_unchanged.value == initial_value
                    assert observer.query(models.AuditLog).filter(
                        models.AuditLog.event_type == audit_event
                    ).count() == 0
            finally:
                # Always release the row lock, including on test failures.
                reader.commit()

            response = future.result(timeout=12)

    assert response.status_code == 200, response.text
    assert response.json()["admin_paused"] is (action == "pause")
    with SessionLocal() as check:
        setting = check.scalar(
            select(models.Setting).where(models.Setting.key == "admin_paused")
        )
        assert setting is not None and setting.value == final_value
        assert check.query(models.AuditLog).filter(
            models.AuditLog.event_type == audit_event
        ).count() == 1
        assert check.query(models.AuditLog).count() == 1
        assert check.query(models.Command).count() == 0
        assert check.query(models.Execution).count() == 0
