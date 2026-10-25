"""FastAPI application entrypoint for SignalGate backend."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from .config import get_settings, local_demo_http_ingress_is_loopback
from .database import SessionLocal, init_db
from .routes import admin, commands, ea, health, provider_sources, providers, signals, users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signalgate")
request_logger = logging.getLogger("signalgate.request")
settings = get_settings()

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
    settings.validate_startup()
    init_db()
    seed_settings()
    logger.info("SignalGate backend ready (demo-only mode).")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="SignalGate",
        description=(
            "Telegram-to-MetaTrader 5 DEMO trade execution system. "
            "Demo only. No live trading."
        ),
        version="1.0.0",
        lifespan=_lifespan,
    )

    @app.middleware("http")
    async def _request_observability(request: Request, call_next):
        # Uvicorn may be invoked with --host independently of BACKEND_HOST.
        # Reject nonlocal actual ASGI listeners and nonlocal Host values before
        # dispatching any route that trusts local identity headers. This cannot
        # identify a reverse proxy that rewrites Host to loopback; local mode
        # must still never be exposed through an external proxy.
        host_values = request.headers.getlist("host")
        if not settings.require_license and (
            len(host_values) != 1
            or not local_demo_http_ingress_is_loopback(
                request.scope.get("server"), host_values[0]
            )
        ):
            return PlainTextResponse("Local demo ingress refused", status_code=403)

        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            request_logger.exception(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "latency_ms": latency_ms,
                    },
                    separators=(",", ":"),
                )
            )
            raise

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        request_logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "latency_ms": latency_ms,
                },
                separators=(",", ":"),
            )
        )
        return response

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        """Send browser users to the local API console.

        This is not a public landing page; it just prevents the local backend
        root from looking broken when opened in a browser.
        """
        return RedirectResponse(url="/docs")

    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(signals.router)
    app.include_router(commands.router)
    app.include_router(ea.router)
    app.include_router(admin.router)
    app.include_router(providers.router)
    app.include_router(provider_sources.router)
    return app


app = create_app()
