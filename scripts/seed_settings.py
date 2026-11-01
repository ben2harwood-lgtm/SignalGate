"""Seed (or re-seed) default settings rows without touching tables."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(_HERE, "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

from app.config import Settings  # noqa: E402


def main() -> None:
    # Fail before importing the engine/models or performing any schema/seed I/O.
    preflight = Settings()
    preflight.validate_cli_bootstrap()

    from app.database import init_db, settings as loaded_settings
    from app.main import seed_settings

    if (
        loaded_settings.database_url != preflight.database_url
        or loaded_settings.require_license != preflight.require_license
        or loaded_settings.demo_only_mode != preflight.demo_only_mode
    ):
        raise RuntimeError("Refusing CLI bootstrap: database settings changed after preflight.")
    loaded_settings.validate_cli_bootstrap()

    init_db()
    seed_settings()
    print("Default settings seeded.")


if __name__ == "__main__":
    main()
