"""Seed (or re-seed) default settings rows without touching tables."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_HERE, "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

from app.database import init_db  # noqa: E402
from app.main import seed_settings  # noqa: E402


def main() -> None:
    init_db()
    seed_settings()
    print("Default settings seeded.")


if __name__ == "__main__":
    main()
