"""Fail-closed launcher for the publicly bindable hosted *demo-only* image.

The Dockerfile always executes this module before the existing Uvicorn CLI.
This is defence in depth, not a substitute for in-app deployment validation:
a manually invoked Uvicorn process outside the image still requires issue #108.
"""
from __future__ import annotations

import os

from .config import Settings

_UVICORN_ARGS = (
    "uvicorn", "app.main:app", "--host", "0.0.0.0",
    "--port", "8000", "--proxy-headers",
)


def validate_hosted_entrypoint(settings: Settings) -> None:
    """Refuse the local-header auth model in the hosted distribution image."""
    if not settings.require_license:
        raise RuntimeError(
            "The hosted image requires REQUIRE_LICENSE=true; "
            "local demo identity-header mode is refused."
        )
    settings.validate_startup()


def main() -> None:
    try:
        validate_hosted_entrypoint(Settings())
    except RuntimeError as exc:
        # The validation errors contain configuration *names*, not secret values.
        raise SystemExit(f"SignalGate hosted startup refused: {exc}") from None
    os.execvp(_UVICORN_ARGS[0], list(_UVICORN_ARGS))


if __name__ == "__main__":
    main()
