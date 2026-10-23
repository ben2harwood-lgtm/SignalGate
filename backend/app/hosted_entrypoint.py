"""Fail-closed launcher for the publicly bindable hosted *demo-only* image.

The Dockerfile always executes this module before the existing Uvicorn CLI.
This is defence in depth, not a substitute for in-app deployment validation:
a manually invoked Uvicorn process outside the image still requires issue #108.
"""
from __future__ import annotations

import os

from .config import Settings

def validate_hosted_entrypoint(settings: Settings) -> None:
    """Refuse the local-header auth model in the hosted distribution image."""
    if not settings.require_license:
        raise RuntimeError(
            "The hosted image requires REQUIRE_LICENSE=true; "
            "local demo identity-header mode is refused."
        )
    settings.validate_startup()


def main() -> None:
    settings = Settings()
    try:
        validate_hosted_entrypoint(settings)
    except RuntimeError as exc:
        # The validation errors contain configuration *names*, not secret values.
        raise SystemExit(f"SignalGate hosted startup refused: {exc}") from None

    # The image defaults to Settings' loopback bind. Staging must explicitly
    # select a container-internal interface with BACKEND_HOST; ports are bound
    # to the host's loopback by compose.staging.yml, never an open host port.
    argv = [
        "uvicorn", "app.main:app", "--host", settings.backend_host,
        "--port", "8000", "--proxy-headers",
    ]
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
