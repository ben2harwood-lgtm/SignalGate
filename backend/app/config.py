"""Application configuration loaded from environment variables.

For the local prototype we keep this simple: read a .env file if present and
fall back to sane demo-only defaults. Nothing here should ever default to a
live-trading configuration.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

# Load the project .env (search up from CWD). Safe to call repeatedly.
load_dotenv()


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    """Plain settings object (no external dependency on pydantic-settings).

    Kept as a simple class so tests can construct/override easily.
    """

    def __init__(self) -> None:
        # DATABASE_URL drives which database is used. SQLite for local demo,
        # PostgreSQL for the hosted/multi-customer deployment. Many managed
        # Postgres providers hand out a "postgres://" URL, which SQLAlchemy no
        # longer accepts — normalise it to the "postgresql://" form here.
        raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./signalgate.db")
        if raw_db_url.startswith("postgres://"):
            raw_db_url = "postgresql://" + raw_db_url[len("postgres://"):]
        self.database_url: str = raw_db_url
        self.backend_host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
        self.backend_port: int = _get_int("BACKEND_PORT", 8000)
        self.backend_base_url: str = os.getenv(
            "BACKEND_BASE_URL", "http://127.0.0.1:8000"
        )

        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        admin_ids_raw: str = os.getenv("ADMIN_TELEGRAM_IDS", "")
        self.admin_telegram_ids: List[str] = [
            x.strip() for x in admin_ids_raw.split(",") if x.strip()
        ]
        provider_ids_raw: str = os.getenv("SIGNAL_PROVIDER_TELEGRAM_IDS", "")
        self.signal_provider_telegram_ids: List[str] = [
            x.strip() for x in provider_ids_raw.split(",") if x.strip()
        ]

        self.ea_api_key: str = os.getenv("EA_API_KEY", "local-demo-ea-key")

        # HARDENING (hosted): real secrets, distinct from the spoofable
        # Telegram-id headers. When set, they become the required credential
        # (see security.py); when unset, local demo/test behaviour is unchanged.
        #  - admin_api_token gates every /admin/* route (X-Admin-Token header).
        #  - bot_backend_secret authenticates the Telegram bot to the backend
        #    on the endpoints it proxies (approve/reject/register/user-lookup)
        #    via the X-Bot-Secret header, so a public server can't be driven by
        #    anyone who simply knows a Telegram id.
        self.admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "")
        self.bot_backend_secret: str = os.getenv("BOT_BACKEND_SECRET", "")

        # Hide interactive API docs (/docs, /redoc, OpenAPI) on a public server.
        self.expose_docs: bool = _get_bool("EXPOSE_DOCS", True)

        # Per-IP request cap for public/expensive endpoints (0 disables).
        self.rate_limit_per_minute: int = _get_int("RATE_LIMIT_PER_MINUTE", 60)

        # Optional whitelist of tradeable symbols (comma-separated, e.g.
        # "EURUSD,GBPJPY,XAUUSD"). Empty = allow every symbol the parser
        # recognises (all forex pairs, metals, and supported crypto). Set this
        # to restrict a desk to just the pairs a given provider trades.
        symbols_raw: str = os.getenv("ALLOWED_SYMBOLS", "")
        self.allowed_symbols = {
            s.strip().upper() for s in symbols_raw.split(",") if s.strip()
        } or None

        # HOSTED MULTI-CUSTOMER: when true, an EA must present a valid, ACTIVE
        # customer license_key to receive commands; the local user_id fallback
        # is disabled. Defaults False so the local demo keeps working unchanged.
        self.require_license: bool = _get_bool("REQUIRE_LICENSE", False)

        # SAFETY: demo-only mode defaults to True and should never be flipped
        # off for v1. Live trading is explicitly unsupported.
        self.demo_only_mode: bool = _get_bool("DEMO_ONLY_MODE", True)

        self.default_signal_expiry_minutes: int = _get_int(
            "DEFAULT_SIGNAL_EXPIRY_MINUTES", 5
        )
        self.default_lot_size: float = _get_float("DEFAULT_LOT_SIZE", 0.01)
        self.split_ticket_demo_partial_mode: bool = _get_bool(
            "SPLIT_TICKET_DEMO_PARTIAL_MODE", True
        )
        self.tp1_lot: float = _get_float("TP1_LOT", 0.02)
        self.tp2_lot: float = _get_float("TP2_LOT", 0.01)
        self.tp3_lot: float = _get_float("TP3_LOT", 0.01)
        self.max_spread_points: int = _get_int("MAX_SPREAD_POINTS", 500)
        self.max_slippage_points: int = _get_int("MAX_SLIPPAGE_POINTS", 100)

    def is_admin(self, telegram_user_id: str) -> bool:
        return str(telegram_user_id) in self.admin_telegram_ids

    def is_signal_provider(self, telegram_user_id: str) -> bool:
        user_id = str(telegram_user_id)
        return (
            user_id in self.admin_telegram_ids
            or user_id in self.signal_provider_telegram_ids
        )

    def hosted_config_errors(self) -> list[str]:
        """Fail-closed checks for a public deployment.

        Hosted posture is signalled by REQUIRE_LICENSE=true. In that mode the
        server must NOT boot with the local-demo defaults or missing secrets,
        or a public box would ship with spoofable admin auth, an open bot
        surface, and the shipped EA key. Returns a list of problems (empty = ok).
        """
        if not self.require_license:
            return []
        errors: list[str] = []
        if not self.admin_api_token or len(self.admin_api_token) < 24:
            errors.append("ADMIN_API_TOKEN must be set to a strong value (>=24 chars)")
        if not self.bot_backend_secret or len(self.bot_backend_secret) < 24:
            errors.append("BOT_BACKEND_SECRET must be set to a strong value (>=24 chars)")
        if not self.ea_api_key or self.ea_api_key == "local-demo-ea-key":
            errors.append("EA_API_KEY must be changed from the local-demo default")
        if self.expose_docs:
            errors.append("EXPOSE_DOCS should be false on a public server")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
