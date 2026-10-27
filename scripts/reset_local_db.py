"""Destructively reset the canonical LOCAL demo SQLite database only.

Do not use on a hosted system or with a customer/production database.
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "backend"


def _require_local_demo_target(
    database_url: str,
    *,
    demo_only_mode: bool,
    require_license: bool,
    cwd: Path | None = None,
) -> Path:
    """Return the approved local demo path or refuse without revealing a DSN.

    Reject every non-SQLite engine, URL query/URI mode, memory database, and
    alternate path. This intentionally supports only the demo database named
    ``signalgate.db`` in the project root or its backend/ directory.
    """
    if not demo_only_mode or require_license:
        raise RuntimeError("Refusing reset outside unlicensed demo-only mode.")

    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError, TypeError):
        raise RuntimeError("Refusing reset: invalid local SQLite database URL.") from None

    if (
        url.drivername != "sqlite"
        or url.query
        or url.host is not None
        or url.username is not None
        or url.password is not None
        or url.port is not None
        or not url.database
        or url.database == ":memory:"
    ):
        raise RuntimeError("Refusing reset: only the local demo SQLite file is allowed.")

    path = Path(url.database)
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    # SQLite's pysqlite dialect normalizes relative/absolute filenames using
    # os.path.abspath *before* filesystem lookup. pathlib.resolve alone can
    # follow a directory symlink before collapsing '..', approving a DIFFERENT
    # file from the one the SQLite driver actually opens. Match the driver.
    driver_path = Path(os.path.abspath(str(path)))
    approved = {
        _ROOT / "signalgate.db",
        _BACKEND / "signalgate.db",
    }
    if driver_path.is_symlink():
        raise RuntimeError("Refusing reset: local demo database must not be a symlink.")
    target = driver_path.resolve()
    if target not in approved:
        raise RuntimeError("Refusing reset: database is not the canonical local demo file.")

    # The SQLite engine opens this pathname after preflight, not an already
    # validated file descriptor. Refuse directories another local principal can
    # replace, and never reset an aliased inode through a hardlink. This only
    # mitigates cross-account local file swaps; the CLI still requires a trusted
    # operator and cannot defend against a hostile process using the same UID.
    if os.name == "posix":
        directory_info = driver_path.parent.stat()
        if directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o022:
            raise RuntimeError("Refusing reset: local demo database directory must be private.")
    try:
        file_info = driver_path.lstat()
    except FileNotFoundError:
        pass  # A fresh local demo database has not been created yet.
    else:
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_nlink != 1:
            raise RuntimeError("Refusing reset: database must be a single-link regular file.")
        if os.name == "posix" and file_info.st_uid != os.geteuid():
            raise RuntimeError("Refusing reset: demo database must be owned by the operator.")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-local-demo-reset",
        action="store_true",
        help="Explicitly authorise destruction of the canonical local demo SQLite data.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_local_demo_reset:
        parser.error("Refusing destructive reset without --confirm-local-demo-reset.")

    # Import configuration only after operator confirmation. Critically, never
    # import the engine, models or seed functions until preflight has passed.
    sys.path.insert(0, str(_BACKEND))
    from app.config import Settings

    settings = Settings()
    target = _require_local_demo_target(
        settings.database_url,
        demo_only_mode=settings.demo_only_mode,
        require_license=settings.require_license,
    )

    # The SQLite driver captures its absolute filename during engine creation,
    # but engine.url can retain a relative URL. If this module was imported
    # before the preflight (possibly in a different working directory), its
    # actual cached connection target cannot be established from engine.url.
    # This destructive CLI must start in a fresh process with no cached engine.
    if "app.database" in sys.modules:
        raise RuntimeError(
            "Refusing reset: pre-existing database engine cannot be verified."
        )

    # Import only after the caller's filename and policy are validated. The
    # current working directory stays fixed while the engine binds its target.
    from app.database import Base, engine, init_db, settings as engine_settings
    from app.main import seed_settings

    active = _require_local_demo_target(
        str(engine.url),
        demo_only_mode=engine_settings.demo_only_mode,
        require_license=engine_settings.require_license,
    )
    if active != target:
        raise RuntimeError("Refusing reset: database engine target changed since preflight.")

    print("Destroying and recreating the canonical LOCAL demo SQLite data...")
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed_settings()
    print("Local demo database reset and re-seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
