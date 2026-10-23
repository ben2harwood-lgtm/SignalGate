"""Destructively reset the canonical LOCAL demo SQLite database only.

Do not use on a hosted system or with a customer/production database.
"""
from __future__ import annotations

import argparse
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
    target = path.resolve()
    approved = {
        (_ROOT / "signalgate.db").resolve(),
        (_BACKEND / "signalgate.db").resolve(),
    }
    if target not in approved:
        raise RuntimeError("Refusing reset: database is not the canonical local demo file.")
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

    # The database module holds an engine created from cached settings. Check
    # the *actual* engine target as well in case another module initialised it
    # earlier with different environment values.
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
