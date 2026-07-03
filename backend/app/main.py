"""FastAPI application entrypoint for SignalGate backend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

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
    return app


app = create_app()
