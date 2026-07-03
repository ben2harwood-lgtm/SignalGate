"""Initialise the SignalGate database and seed default settings.

Run from the backend directory (so `app` is importable):
    cd backend && python ../scripts/init_db.py
"""
from __future__ import annotations

import os
import sys

# Make the backend package importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_HERE, "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

from app.database import init_db  # noqa: E402
from app.main import seed_settings  # noqa: E402


def main() -> None:
    init_db()
    seed_settings()
    print("SignalGate database initialised and settings seeded (demo-only).")


if __name__ == "__main__":
    main()
