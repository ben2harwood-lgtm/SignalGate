"""Offline PostgreSQL proof of the row-lock mode needed for pause safety.

A pause writes a non-key boolean column. On PostgreSQL, FOR KEY SHARE does
not block that UPDATE; FOR SHARE does. This is a *database lock contract*
test, not proof that the application has acquired either lock. The existing
paused-screenshot and signal-creation XFAILs remain release blockers.

Only isolated synthetic provider/feed rows and local database sessions are
used. No image model, broker, Telegram, execution or external service.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import event, select, text as sql_text

from app import models
from app.database import SessionLocal

from .test_provider_sources import _provider


@pytest.mark.parametrize("scope_name", ("provider", "feed"))
@pytest.mark.parametrize(
    ("mode", "writer_must_wait"),
    (("share", True), ("key_share", False)),
)
def test_postgresql_pause_update_conflicts_with_correct_shared_lock(
    db, scope_name, mode, writer_must_wait
):
    """Prove actual commit ordering, not merely generated SQL spelling.

    FOR SHARE must hold a paused-field UPDATE until the read transaction
    commits. FOR KEY SHARE must *not* be treated as a substitute. An event
    confirms the second transaction actually attempted UPDATE before its
    outcome is inspected. Bounded PostgreSQL/Python timeouts prevent hangs.
    """
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Requires real PostgreSQL row-lock compatibility")

    provider, feed, _key = _provider(
        db, f"pause-lock-mode-{scope_name}-{mode}"
    )
    model = models.Provider if scope_name == "provider" else models.Feed
    target_id = provider.id if scope_name == "provider" else feed.id

    reader_has_lock = Event()
    release_reader = Event()
    writer_update_attempted = Event()
    writer_committed = Event()
    reader_backend_pid: list[int] = []
    writer_backend_pid: list[int] = []

    def locked_reader():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")
            reader_backend_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            statement = (
                select(model)
                .where(model.id == target_id)
                .with_for_update(
                    read=True,
                    key_share=(mode == "key_share"),
                )
            )
            row = session.scalar(statement)
            assert row is not None
            assert row.status == "ACTIVE"
            assert row.paused is False
            reader_has_lock.set()
            try:
                assert release_reader.wait(timeout=15), (
                    "Concurrency coordinator never released locked reader"
                )
            finally:
                # Committing releases the PostgreSQL row lock even if the
                # test coordinator fails; never leave a blocked writer.
                session.commit()

    def pause_writer():
        with SessionLocal() as session:
            conn = session.connection()
            conn.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
            conn.exec_driver_sql("SET LOCAL statement_timeout = '12s'")

            writer_backend_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())

            def observed_update(_conn, _cursor, sql, _params, _ctx, _many):
                if sql.lstrip().lower().startswith(
                    f"update {model.__tablename__} set"
                ):
                    writer_update_attempted.set()

            event.listen(conn, "before_cursor_execute", observed_update)
            row = session.get(model, target_id)
            assert row is not None
            assert row.paused is False
            row.paused = True
            session.commit()
            committed_before_release = not release_reader.is_set()
            writer_committed.set()
            return committed_before_release

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = pool.submit(locked_reader)
        try:
            assert reader_has_lock.wait(timeout=8), (
                "Reader did not acquire the real PostgreSQL lock"
            )
            write_future = pool.submit(pause_writer)
            assert writer_update_attempted.wait(timeout=8), (
                "Independent writer did not attempt paused-field UPDATE"
            )
            # Do not mistake a slow test worker for a real row lock. For
            # FOR SHARE, query the server's live wait graph and prove that
            # this exact UPDATE is blocked by the reader backend PID.
            # FOR KEY SHARE must let the same UPDATE commit before release.
            if writer_must_wait:
                with SessionLocal() as observer:
                    deadline = monotonic() + 4.0
                    while monotonic() < deadline:
                        blockers = observer.scalar(
                            sql_text("SELECT pg_blocking_pids(:writer_pid)"),
                            {"writer_pid": writer_backend_pid[0]},
                        )
                        if reader_backend_pid[0] in blockers:
                            break
                        sleep(0.05)
                    else:
                        pytest.fail(
                            f"{scope_name} {mode}: PostgreSQL did not report "
                            "the reader as the pause UPDATE blocker"
                        )
                assert not writer_committed.is_set(), (
                    f"{scope_name} {mode}: pause committed despite row lock"
                )
            else:
                assert writer_committed.wait(timeout=8), (
                    f"{scope_name} {mode}: pause UPDATE did not commit "
                    "under FOR KEY SHARE before reader release"
                )
        finally:
            release_reader.set()
        read_future.result(timeout=18)
        overtook = write_future.result(timeout=18)

    assert overtook is (not writer_must_wait)
    with SessionLocal() as check:
        row = check.get(model, target_id)
        assert row is not None
        assert row.status == "ACTIVE"
        assert row.paused is True
        # This test only proves lock compatibility, not execution safety.
        assert check.query(models.Command).count() == 0
        assert check.query(models.Execution).count() == 0
