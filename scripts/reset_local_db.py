"""Drop and recreate all tables, then re-seed settings. LOCAL DEV ONLY.

This permanently deletes the local SQLite data. Demo data only.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_HERE, "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

from app.database import Base, engine, init_db  # noqa: E402
from app.main import seed_settings  # noqa: E402


def main() -> None:
    print("Dropping all tables (local demo data)...")
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed_settings()
    print("Local database reset and re-seeded.")


if __name__ == "__main__":
    main()
