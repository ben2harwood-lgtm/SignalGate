"""FastAPI application entrypoint for SignalGate backend."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import get_settings
from .database import SessionLocal, init_db
from .routes import admin, commands, ea, health, signals, users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signalgate")

# Default settings seeded on first run.
DEFAULT_SETTINGS = {
    "admin_paused": "false",
    "default_signal_expiry_minutes": "5",
    "max_spread": "500",
    "max_slippage": "100",
    "demo_only_mode": "true",
    "default_lot_size": "0.01",
    "split_ticket_demo_partial_mode": "true",
    "tp1_lot": "0.02",
    "tp2_lot": "0.01",
    "tp3_lot": "0.01",
    "tp1_close_percent": "50",
    "tp2_close_percent": "25",
    "tp3_close_percent": "25",
}


def seed_settings() -> None:
    """Idempotently seed default settings rows."""
    from . import crud

    db = SessionLocal()
    try:
        for key, value in DEFAULT_SETTINGS.items():
            if crud.get_setting(db, key) is None:
                crud.set_setting(db, key, value)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # FAIL-CLOSED: a public (hosted) deployment must not boot with local-demo
    # defaults or missing secrets. Refuse to start with a clear message rather
    # than silently exposing spoofable admin auth / an open bot surface.
    errors = settings.hosted_config_errors()
    if errors:
        joined = "\n  - ".join(errors)
        raise RuntimeError(
            "Refusing to start: hosted mode (REQUIRE_LICENSE=true) is "
            f"misconfigured:\n  - {joined}"
        )
    init_db()
    seed_settings()
    logger.info("SignalGate backend ready (demo-only mode).")
    yield


# --- Simple in-process per-IP rate limiter --------------------------------
# Protects public/expensive endpoints (registration, approve/reject, and the
# paid screenshot-extract call) from abuse on a public server. In-process only
# (per worker) — enough for a single-VPS deployment; a multi-worker setup would
# move this to Redis. Read-only and EA-key'd endpoints are exempt.
_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)
_RATE_LIMITED_PREFIXES = ("/register_user", "/signals/")


def _client_ip(request: Request) -> str:
    # Behind Caddy/nginx the real client is in X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app() -> FastAPI:
    settings = get_settings()
    # Hide interactive docs + schema on a public server (no attack-surface map).
    docs_kwargs = (
        {}
        if settings.expose_docs
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = FastAPI(
        title="SignalGate",
        description=(
            "Telegram-to-MetaTrader 5 DEMO trade execution system. "
            "Demo only. No live trading."
        ),
        version="1.0.0",
        lifespan=_lifespan,
        **docs_kwargs,
    )

    @app.middleware("http")
    async def _security_and_rate_limit(request: Request, call_next):
        limit = settings.rate_limit_per_minute
        path = request.url.path
        if limit > 0 and any(path.startswith(p) for p in _RATE_LIMITED_PREFIXES):
            now = time.monotonic()
            bucket = _RATE_BUCKETS[_client_ip(request)]
            while bucket and now - bucket[0] > 60.0:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests; slow down."},
                )
            bucket.append(now)
        response = await call_next(request)
        # Baseline hardening headers (cheap; harmless behind Caddy TLS).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        """Send browser users to the API console (local) or health (hosted)."""
        return RedirectResponse(url="/docs" if settings.expose_docs else "/health")

    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(signals.router)
    app.include_router(commands.router)
    app.include_router(ea.router)
    app.include_router(admin.router)
    return app


app = create_app()
