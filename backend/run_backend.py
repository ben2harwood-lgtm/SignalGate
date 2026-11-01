"""Local-only development launcher; use the hosted entrypoint for hosted mode."""
from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    settings.validate_startup()
    if settings.require_license:
        raise RuntimeError("Development launcher is local-only; use the hardened hosted entrypoint.")
    if not settings.database_url.startswith(("sqlite://", "sqlite+pysqlite://")):
        raise RuntimeError("Local demo launcher requires SQLite; PostgreSQL needs hosted auth.")
    if settings.backend_host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("Local demo launcher must bind a numeric loopback host.")
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
