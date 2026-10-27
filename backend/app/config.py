"""Application configuration loaded from environment variables.

For the local prototype we keep this simple: read a .env file if present and
fall back to sane demo-only defaults. Nothing here should ever default to a
live-trading configuration.
"""
from __future__ import annotations

import os
from functools import lru_cache
from ipaddress import ip_address
from typing import List, Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv

# Load the project .env (search up from CWD). Safe to call repeatedly.
load_dotenv()


def sqlalchemy_driver_url(database_url: str) -> str:
    """Choose the installed psycopg2 dialect without changing the operator DSN.

    SQLAlchemy 2.1 changes the default driver for postgresql://. Our hosted
    dependency and migration/restore tooling still use psycopg2-binary. Keep
    DATABASE_URL unchanged for libpq, psql and the backup/restore scripts;
    only SQLAlchemy/Alembic engine construction needs an explicit dialect.
    Explicit driver schemes and SQLite remain unchanged.
    """
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + database_url[len("postgresql://"):]
    return database_url


def _is_loopback_host(host: str) -> bool:
    """Never resolve arbitrary hostnames when guarding local header auth."""
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _local_demo_base_url_is_loopback(value: str) -> bool:
    """Reject externally advertised URLs without accepting deceptive hosts."""
    try:
        parts = urlsplit(value)
        # Accessing .port also validates malformed port syntax.
        _ = parts.port
        return (
            parts.scheme in {"http", "https"}
            and bool(parts.netloc)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and _is_loopback_host(parts.hostname or "")
        )
    except (TypeError, ValueError):
        return False



def local_demo_http_ingress_is_loopback(server: object, host_header: Optional[str]) -> bool:
    """Conservatively check the actual ASGI bound endpoint and HTTP Host.

    BACKEND_HOST describes the intended listener, not a manually overridden
    Uvicorn --host. The ASGI server tuple is independent of a spoofed Host.
    Reject unknown/non-TCP binds and nonlocal/malformed Host values instead
    of trusting either signal alone. This is defence in depth, not a proxy
    security boundary: a proxy rewriting Host to loopback can mask the client.
    """
    if (
        not isinstance(server, (tuple, list))
        or len(server) != 2
        or not isinstance(server[0], str)
        or not _is_loopback_host(server[0])
        or not isinstance(host_header, str)
        or not host_header
        or any(ord(c) <= 32 or ord(c) == 127 for c in host_header)
    ):
        return False
    try:
        parsed = urlsplit("http://" + host_header)
        _ = parsed.port  # invalid ports must fail closed
        return (
            parsed.netloc == host_header
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and _is_loopback_host(parsed.hostname)
        )
    except (TypeError, ValueError):
        return False


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
        self.admin_api_key: str = os.getenv("ADMIN_API_KEY", "")
        self.signal_provider_api_key: str = os.getenv("SIGNAL_PROVIDER_API_KEY", "")
        self.registration_api_key: str = os.getenv("REGISTRATION_API_KEY", "")

        symbols_raw = os.getenv("ALLOWED_SYMBOLS", "")
        self.allowed_symbols: Optional[set[str]] = (
            {s.strip().upper() for s in symbols_raw.split(",") if s.strip()}
            or None
        )

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

    def validate_startup(self) -> None:
        """Fail closed when a hosted deployment is configured unsafely.

        Local demo mode intentionally remains frictionless. Hosted mode is
        identified by REQUIRE_LICENSE=true and requires HTTPS, PostgreSQL and
        non-placeholder server secrets. SignalGate remains demo-only in this
        release; setting DEMO_ONLY_MODE=false is a hard startup error.
        """
        if not self.demo_only_mode:
            raise RuntimeError(
                "SignalGate hardening release is DEMO ONLY; DEMO_ONLY_MODE must be true."
            )

        if not self.require_license:
            # Header-only local-demo identities are never suitable for an
            # explicitly public bind or advertised API URL. This protects
            # normal settings-driven launches, but cannot discover a manually
            # overridden Uvicorn bind or an undisclosed reverse proxy.
            if (
                not _is_loopback_host(self.backend_host)
                or not _local_demo_base_url_is_loopback(self.backend_base_url)
            ):
                raise RuntimeError(
                    "Unlicensed local demo requires loopback "
                    "BACKEND_HOST and BACKEND_BASE_URL."
                )
            return

        if self.database_url.startswith("sqlite"):
            raise RuntimeError("Hosted mode requires PostgreSQL; SQLite is not supported.")
        if not self.backend_base_url.lower().startswith("https://"):
            raise RuntimeError("Hosted mode requires an HTTPS BACKEND_BASE_URL.")

        weak = {
            "",
            "replace_me",
            "changeme",
            "change_me",
            "local-demo-ea-key",
            "test-ea-key",
        }
        required = {
            "EA_API_KEY": self.ea_api_key,
            "ADMIN_API_KEY": self.admin_api_key,
            "REGISTRATION_API_KEY": self.registration_api_key,
        }
        for name, value in required.items():
            normalised = value.strip().lower()
            if normalised in weak or len(value.strip()) < 32:
                raise RuntimeError(
                    f"Hosted mode requires a strong {name} (minimum 32 characters)."
                )

    def validate_cli_bootstrap(self) -> None:
        """Fail closed for standalone database bootstrap commands.

        The unlicensed bootstrap CLI is for local file-backed SQLite only.
        Hosted bootstrap still requires validate_startup() and the existing
        migration check in app.database.init_db(). This is a *CLI* boundary; other partial app-level guards do not
        establish public network or reverse-proxy isolation (issue #108).
        """
        self.validate_startup()
        if self.require_license:
            return

        from sqlalchemy.engine import make_url
        from sqlalchemy.exc import ArgumentError

        try:
            url = make_url(self.database_url)
        except (ArgumentError, TypeError, ValueError):
            raise RuntimeError("Refusing CLI bootstrap: invalid database URL.") from None

        if (
            url.drivername != "sqlite"
            or url.database in (None, "", ":memory:")
            or bool(url.query)
            or url.host is not None
            or url.username is not None
            or url.password is not None
            or url.port is not None
        ):
            raise RuntimeError(
                "Refusing CLI bootstrap: unlicensed mode requires a local SQLite file."
            )

    def is_admin(self, telegram_user_id: str) -> bool:
        return str(telegram_user_id) in self.admin_telegram_ids

    def is_signal_provider(self, telegram_user_id: str) -> bool:
        user_id = str(telegram_user_id)
        return (
            user_id in self.admin_telegram_ids
            or user_id in self.signal_provider_telegram_ids
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
