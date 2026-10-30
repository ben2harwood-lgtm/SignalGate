"""Telegram command and callback handlers.

The bot is a thin client over the backend HTTP API. It performs NO trading
logic itself — all decisions, idempotency and safety live in the backend.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
import secrets
import unicodedata
from typing import Any, Dict, List, Optional

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from config import config

logger = logging.getLogger("signalgate.bot")

# Decision result code -> message shown to the user (precise outcomes).
DECISION_MESSAGES = {
    "APPROVED": "Approved. Waiting for MetaTrader EA to execute demo trade.",
    "REJECTED": "Rejected. No trade command created.",
    "ALREADY_APPROVED": "Already approved. No duplicate command created.",
    "ALREADY_REJECTED": "Already rejected. No command created.",
    "SIGNAL_EXPIRED": "Signal expired. No command created.",
    "TRADING_PAUSED": "Trading paused. No command created.",
    "PARSER_REJECTED": "Parser rejected signal. No command created.",
    "USER_NOT_FOUND": "You are not registered. Send /start first.",
    "USER_INACTIVE": "Your account is not active.",
    "SIGNAL_NOT_FOUND": "Signal not found.",
    "TENANT_INVALID": "Signal provider/feed ownership could not be verified. No command created.",
    "TENANT_INACTIVE": "Signal provider or feed is inactive. No command created.",
    "PROVIDER_PAUSED": "Provider paused. No command created.",
    "FEED_PAUSED": "Feed paused. No command created.",
    "NOT_SUBSCRIBED": "You are not subscribed to this feed. No command created.",
    "ACCOUNT_NOT_FOUND": "No active provider trading account found. No command created.",
}

# The backend YES/NO routes have different permissible outcomes. A known code
# from the wrong endpoint is still a contradictory receipt, not permission to
# tell a subscriber that a different decision was recorded.
DECISION_ALLOWED_BY_ACTION = {
    "YES": frozenset(DECISION_MESSAGES) - {"REJECTED"},
    "NO": frozenset({
        "REJECTED", "ALREADY_REJECTED", "ALREADY_APPROVED",
        "USER_NOT_FOUND", "SIGNAL_NOT_FOUND",
    }),
}


def _valid_signal_id(value: Any) -> bool:
    """Only backend-issued signal identifiers may enter callback paths/cards."""
    # Current hosted IDs are SIG- plus 16 uppercase hex characters; retain
    # older numeric demo IDs, while refusing delimiters and Unicode lookalikes.
    return (
        isinstance(value, str)
        and re.fullmatch(r"SIG-[A-Z0-9]{1,32}", value, flags=re.ASCII) is not None
    )



def _safe_trade_card_signal(signal: Dict[str, Any]) -> bool:
    """Fail closed on malformed HTTP 200 data before displaying an approval card.

    SignalOut's VALID market signals contain a bounded symbol, BUY/SELL and
    finite positive numeric price levels. Never turn untrusted JSON strings,
    Unicode controls or non-finite numbers into a subscriber's safety message.
    This is display validation, not a substitute for backend parser authority.
    """
    symbol = signal.get("symbol")
    entry_type = signal.get("entry_type")
    entry_price = signal.get("entry_price")
    if (
        type(symbol) is not str
        or re.fullmatch(r"[A-Za-z0-9#._-]{1,40}", symbol, flags=re.ASCII) is None
        or signal.get("direction") not in ("BUY", "SELL")
        or entry_type not in ("MARKET", "LIMIT")
        or (entry_type == "MARKET" and entry_price is not None)
        or (entry_type == "LIMIT" and entry_price is None)
    ):
        return False
    # LIMIT remains a preview-only shape; its numeric entry is range-checked
    # with the other price fields below. The demo EA separately refuses LIMIT.

    for field in ("initial_stop_loss", "tp1", "tp2", "tp3", "entry_price"):
        value = signal.get(field)
        if value is None and field not in ("initial_stop_loss", "tp1"):
            continue
        # Test the numeric range before math.isfinite: huge hostile JSON ints
        # must be refused without an int-to-float overflow.
        if (
            type(value) not in (int, float)
            or not (0 < value < 1e12)
            or not math.isfinite(value)
        ):
            return False
    return True

def _persisted_signal_expiry_minutes(signal: Dict[str, Any]) -> Optional[int]:
    """Derive the card policy duration from persisted timestamps, not status.

    Parser expiry precedes the database's created_at stamp by milliseconds;
    accept up to five seconds of write latency around the policy minute.
    """
    timestamps = []
    for field in ("created_at", "expires_at"):
        value = signal.get(field)
        if (
            type(value) is not str
            or re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                r"(?:\.\d{1,6})?(?:Z|\+00:00)?",
                value,
                flags=re.ASCII,
            ) is None
        ):
            return None
        try:
            stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        timestamps.append(stamp)

    seconds = (timestamps[1] - timestamps[0]).total_seconds()
    minutes = round(seconds / 60)
    if not 1 <= minutes <= 1440 or abs(seconds - minutes * 60) > 5:
        return None
    # A VALID status is not authority to broadcast a stale or future-dated
    # receipt. Permit minor backend/bot clock skew, but never let an
    # implausibly future creation timestamp extend a human approval window.
    now = dt.datetime.now(dt.timezone.utc)
    if timestamps[0] > now + dt.timedelta(minutes=1) or timestamps[1] <= now:
        return None
    return minutes


def _private_command_chat(update: Update) -> bool:
    """Keep one-time credentials and registration out of shared Telegram chats."""
    return getattr(getattr(update, "effective_chat", None), "type", None) == "private"


def _safe_registration_license(value: Any) -> bool:
    """One-time EA keys must be bounded, printable ASCII before any reply."""
    return value is None or (
        isinstance(value, str)
        and len(value) <= 128
        and value.isascii()
        and value.isprintable()
    )


def _safe_status_label(value: Any) -> str:
    """Display-only guard: source names are never authority or bot control text."""
    if not isinstance(value, str) or len(value) > 80 or any(
        unicodedata.category(ch).startswith("C")
        or unicodedata.category(ch) in ("Zl", "Zp")
        for ch in value
    ):
        # Validate before strip(): stripping a leading newline/bidi separator
        # must not turn a forged status line into a displayable label.
        return "unavailable"
    return value.strip() or "unavailable"


# --- backend helpers ------------------------------------------------------

# Protected /admin/status 401/403 is an explicit authentication refusal.
# Malformed 2xx JSON, transport failures and 5xx are NOT non-admin evidence.
# Keep this identity sentinel internal; never send it to Telegram.
_ADMIN_STATUS_FORBIDDEN = object()


async def _backend_get(
    path: str, *, distinguish_admin_denial: bool = False, **kwargs
) -> Optional[Any]:
    url = f"{config.backend_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(url, **kwargs)
            if not 200 <= resp.status_code < 300:
                logger.warning("backend GET %s returned HTTP %s", path, resp.status_code)
                if (
                    distinguish_admin_denial
                    and path == "/admin/status"
                    and resp.status_code in (401, 403)
                ):
                    return _ADMIN_STATUS_FORBIDDEN
                return None
            data = resp.json()
            return data if isinstance(data, (dict, list)) else None
    except Exception as exc:  # noqa: BLE001
        # Never emit response bodies, query values or secret-bearing headers.
        logger.warning("backend GET %s failed: %s", path, type(exc).__name__)
        return None


async def _backend_post(path: str, **kwargs) -> Optional[Any]:
    url = f"{config.backend_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(url, **kwargs)
            if not 200 <= resp.status_code < 300:
                logger.warning("backend POST %s returned HTTP %s", path, resp.status_code)
                return None
            data = resp.json()
            return data if isinstance(data, (dict, list)) else None
    except Exception as exc:  # noqa: BLE001
        # Never emit response bodies, query values or secret-bearing headers.
        logger.warning("backend POST %s failed: %s", path, type(exc).__name__)
        return None


def _admin_headers(user_id: int) -> Dict[str, str]:
    headers = {"X-Admin-Id": str(user_id)}
    if config.admin_api_key:
        headers["X-Admin-API-Key"] = config.admin_api_key
    return headers


def _registration_headers() -> Dict[str, str]:
    if not config.registration_api_key:
        return {}
    return {"X-Registration-API-Key": config.registration_api_key}


def _signal_provider_headers(user_id: int) -> Dict[str, str]:
    # Preserve the caller's least-privilege identity. Hosted mode also requires
    # a server-held API secret that never leaves this bot process.
    if config.is_admin(user_id):
        return _admin_headers(user_id)
    headers = {"X-Signal-Provider-Id": str(user_id)}
    if config.signal_provider_api_key:
        headers["X-Signal-Provider-API-Key"] = config.signal_provider_api_key
    return headers


async def _provider_source_status(
    telegram_user_id: int | str,
) -> Optional[Dict[str, Any]]:
    data = await _backend_get(
        "/provider-sources/telegram/status",
        params={"telegram_user_id": str(telegram_user_id)},
        headers=_registration_headers(),
    )
    # A successful HTTP status alone is not provider authority. The backend
    # lookup must return an active, typed Telegram binding for this identity.
    # Treat malformed arrays, error-shaped 200s and revoked/incomplete bindings
    # as disconnected; never fall back to local identity in hosted mode.
    if not isinstance(data, dict) or "detail" in data:
        return None
    if data.get("status") != "ACTIVE" or data.get("source_type") != "TELEGRAM":
        return None
    required_fields = (
        "binding_id", "provider_id", "provider_name", "feed_id", "feed_name",
    )
    if any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in required_fields
    ):
        return None
    # The status receipt must carry the effective expiry used by the server.
    # Null/missing and malformed values cannot safely label a human approval card.
    expiry_minutes = data.get("expiry_minutes")
    if type(expiry_minutes) is not int or not 1 <= expiry_minutes <= 1440:
        return None
    return data


async def _can_submit_provider_signal(update: Update) -> bool:
    if await _provider_source_status(update.effective_user.id):
        return True
    if config.require_license:
        return False
    # Local-demo backwards compatibility only.
    return config.is_signal_provider(update.effective_user.id)



def _source_scope(source: Any) -> Optional[Dict[str, str]]:
    """Return the immutable identity fields used to bind a screenshot preview."""
    fields = ("binding_id", "provider_id", "feed_id")
    if not isinstance(source, dict) or any(
        not isinstance(source.get(field), str) or not source[field].strip()
        for field in fields
    ):
        return None
    return {field: source[field] for field in fields}


async def _preview_source_authorised(
    update: Update, original_scope: Any
) -> bool:
    """A new ACTIVE binding is not authority over another feed's old preview."""
    if original_scope is not None:
        expected = _source_scope(original_scope)
        if expected is None:
            return False
        current = await _provider_source_status(update.effective_user.id)
        return _source_scope(current) == expected
    # Hosted callbacks missing a source snapshot (including pre-upgrade or
    # corrupted in-memory previews) must fail closed.
    if config.require_license:
        return False
    return await _can_submit_provider_signal(update)


# --- user commands --------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Registration and one-time EA licences require a private chat with "
            "SignalGate. Nothing was registered here."
        )
        return
    user = update.effective_user
    source = await _provider_source_status(user.id)
    if source:
        # Binding authority is checked above; its names remain untrusted text.
        provider_name = _safe_status_label(
            source.get("provider_display_name") or source.get("provider_name")
        )
        feed_name = _safe_status_label(source.get("feed_name"))
        await update.message.reply_text(
            f"SignalGate provider source connected to {provider_name} — "
            f"{feed_name}.\n"
            f"Your Telegram id is {user.id}.\n\n"
            "Send a signal screenshot. I will preview the extracted levels and "
            "wait for Confirm before any subscriber card is sent."
        )
        return
    if not config.require_license and config.is_signal_provider(user.id):
        await update.message.reply_text(
            "SignalGate screenshot provider ready.\n"
            f"Your Telegram id is {user.id}.\n\n"
            "Send me a signal screenshot. I will read it, show you the extracted "
            "SL/TP details, and wait for you to Confirm before anything is sent."
        )
    else:
        registration = await _backend_post(
            "/register_user",
            json={
                "telegram_user_id": str(user.id),
                "telegram_username": user.username,
                "first_name": user.first_name,
            },
            headers=_registration_headers(),
        )
        # /start can issue a one-time EA licence. Never show one on an HTTP
        # 200 response unless the backend confirms this exact active user.
        # A failed/ambiguous registration may still have consumed the key.
        if (
            not isinstance(registration, dict)
            or "detail" in registration
            or registration.get("telegram_user_id") != str(user.id)
            or registration.get("status") != "ACTIVE"
            or not isinstance(registration.get("id"), str)
            or not registration["id"].strip()
            or not _safe_registration_license(registration.get("license_key"))
        ):
            await update.message.reply_text(
                "Registration could not be confirmed. Check your account "
                "with the SignalGate operator before trying again."
            )
            return
        license_key = registration.get("license_key")
        message = "SignalGate demo tester registered.\nDemo mode only. No live trades."
        if license_key:
            message += (
                "\n\nYour one-time EA licence is:\n"
                f"{license_key}\n"
                "Keep it private. SignalGate cannot display this key again; "
                "if it is lost, an admin must rotate it."
            )
        if config.require_license:
            message += (
                "\n\nTo submit provider signals, generate a feed-bound source token "
                "in the Provider Portal and send /connectprovider TOKEN."
            )
        await update.message.reply_text(message)


async def join_feed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscriber-consent flow for a provider feed invite."""
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Accept feed invitations in a private chat with SignalGate. "
            "No registration or invitation was submitted here."
        )
        return
    user = update.effective_user
    token = " ".join(context.args).strip() if context.args else ""
    if not token:
        await update.message.reply_text(
            "Usage: /join INVITE_TOKEN\n"
            "Only accept an invite you expected from a signal provider."
        )
        return

    registration = await _backend_post(
        "/register_user",
        json={
            "telegram_user_id": str(user.id),
            "telegram_username": user.username,
            "first_name": user.first_name,
        },
        headers=_registration_headers(),
    )
    # Malformed/other-user registration is not authority to use an invite.
    if (
        not isinstance(registration, dict)
        or "detail" in registration
        or registration.get("telegram_user_id") != str(user.id)
        or registration.get("status") != "ACTIVE"
        or not isinstance(registration.get("id"), str)
        or not registration["id"].strip()
        or not _safe_registration_license(registration.get("license_key"))
    ):
        await update.message.reply_text(
            "I couldn't confirm your SignalGate registration. Nothing was joined."
        )
        return

    result = await _backend_post(
        "/subscriptions/accept",
        json={
            "invite_token": token,
            "telegram_user_id": str(user.id),
        },
        headers=_registration_headers(),
    )
    if result is None:
        # A non-2xx or transport error is not proof the one-use POST was undone.
        await update.message.reply_text(
            "Invite acceptance could not be confirmed. Check feed membership "
            "with your provider before retrying this one-time token."
        )
        return
    if not isinstance(result, dict) or "detail" in result:
        # Do not disclose backend diagnostic/token text in a Telegram reply.
        # An unconfirmed POST may still have consumed the one-time invite.
        await update.message.reply_text(
            "Invite acceptance could not be confirmed. Check feed membership "
            "with your provider before retrying this one-time token."
        )
        return

    required_fields = (
        "subscription_id", "account_id", "provider_id", "provider_name",
        "feed_id", "feed_name",
    )
    if result.get("status") != "ACTIVE" or any(
        not isinstance(result.get(field), str) or not result[field].strip()
        for field in required_fields
    ):
        # A malformed HTTP 200 must not produce a false Joined receipt.
        await update.message.reply_text(
            "Invite acceptance could not be confirmed. Check feed membership "
            "with your provider before retrying this one-time token."
        )
        return

    display_name = result.get("provider_display_name")
    provider_name = (
        display_name
        if isinstance(display_name, str) and display_name.strip()
        else result["provider_name"]
    )
    # A confirmed invite is not authority to display arbitrary backend names.
    provider_label = _safe_status_label(provider_name)
    feed_label = _safe_status_label(result["feed_name"])
    message = (
        f"Joined {provider_label} — {feed_label}.\n"
        "You will only receive cards for feeds you have explicitly joined.\n"
        "Demo mode only. No live trades."
    )
    license_key = registration.get("license_key")
    if isinstance(license_key, str) and license_key:
        message += (
            "\n\nYour one-time EA licence is:\n"
            f"{license_key}\n"
            "Keep it private. SignalGate cannot display it again; "
            "if it is lost, an admin must rotate it."
        )
    await update.message.reply_text(message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # The response can identify a user's private provider/feed binding.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Account and provider/feed status requires a private chat with "
            "SignalGate. No account details were retrieved here."
        )
        return
    user = update.effective_user
    health = await _backend_get("/health")
    source = await _provider_source_status(user.id)

    # A reachable /health endpoint is not proof of a valid health receipt.
    # Reject malformed/error-shaped JSON and bool-like values before display.
    health_verified = (
        isinstance(health, dict)
        and "detail" not in health
        and "error" not in health
        and health.get("status") == "ok"
        and type(health.get("demo_only_mode")) is bool
        and type(health.get("admin_paused")) is bool
    )
    paused = health["admin_paused"] if health_verified else "unknown"
    demo_only = health["demo_only_mode"] if health_verified else "unknown"
    role = _role_name(user.id)
    if source:
        role = "provider source"
    lines = [
        f"Telegram ID: {user.id} (registration not checked)",
        f"Role: {role}",
        f"Backend health verified: {'yes' if health_verified else 'no'}",
        f"Demo only mode: {demo_only}",
        f"Admin paused: {paused}",
    ]
    if not health_verified:
        lines.append(
            "Backend health unconfirmed. Verify demo mode and pause state "
            "with the operator before relying on this status."
        )
    elif demo_only is False:
        lines.append(
            "WARNING: Backend reports demo-only mode disabled. "
            "Do not use SignalGate to trade."
        )
    if source:
        # Binding authority was checked separately. Backend-managed names are
        # still untrusted presentation text and must not spoof status lines.
        provider_label = _safe_status_label(
            source.get("provider_display_name") or source.get("provider_name")
        )
        feed_label = _safe_status_label(source.get("feed_name"))
        feed_id_label = _safe_status_label(source.get("feed_id"))
        lines.extend(
            [
                f"Provider: {provider_label}",
                f"Feed: {feed_label} ({feed_id_label})",
            ]
        )
    elif config.require_license:
        lines.append(
            "Provider submissions require a feed-bound token from the "
            "Provider Portal: /connectprovider TOKEN."
        )
    await update.message.reply_text("\n".join(lines))


async def connect_provider_source(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Consume a one-time provider/feed Telegram source connection token."""
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Connect provider sources in a private chat with SignalGate. "
            "No source token was submitted here."
        )
        return
    user = update.effective_user
    token = " ".join(context.args).strip() if context.args else ""
    if not token:
        await update.message.reply_text(
            "Usage: /connectprovider CONNECTION_TOKEN\n"
            "Generate the token in your SignalGate Provider Portal."
        )
        return
    result = await _backend_post(
        "/provider-sources/telegram/connect",
        json={
            "connection_token": token,
            "telegram_user_id": str(user.id),
        },
        headers=_registration_headers(),
    )
    if result is None or not isinstance(result, dict) or "detail" in result:
        # The POST may have connected the source despite an ambiguous reply.
        # Never echo backend details or advise blind re-use of a one-time token.
        await update.message.reply_text(
            "Provider source connection could not be confirmed. Check its status "
            "in the Provider Portal before requesting another one-time token."
        )
        return
    required_fields = (
        "binding_id", "provider_id", "provider_name", "feed_id", "feed_name",
    )
    if (
        result.get("status") != "ACTIVE"
        or result.get("source_type") != "TELEGRAM"
        or any(
            not isinstance(result.get(field), str) or not result[field].strip()
            for field in required_fields
        )
    ):
        await update.message.reply_text(
            "Provider source connection could not be confirmed. Check its status "
            "in the Provider Portal before requesting another one-time token."
        )
        return
    display_name = result.get("provider_display_name")
    provider_name = (
        display_name
        if isinstance(display_name, str) and display_name.strip()
        else result["provider_name"]
    )
    # Connection authority and Telegram-safe presentation are separate checks.
    provider_label = _safe_status_label(provider_name)
    feed_label = _safe_status_label(result["feed_name"])
    await update.message.reply_text(
        f"Provider source connected to {provider_label} — "
        f"{feed_label}.\n"
        "Send /screenshothelp or send a signal screenshot when ready.\n"
        "Demo mode only."
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Configuration and even generic readiness hints belong in a private chat.
    # Refuse before admin credentials, backend status or public health lookup.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /settings in a private chat with SignalGate. "
            "No settings were retrieved."
        )
        return

    unconfirmed = (
        "Settings could not be confirmed. Verify demo mode and configuration "
        "in the Provider Portal before relying on them."
    )
    # Only an explicit protected-endpoint 401/403 is a non-admin refusal.
    # Unavailable, invalid JSON, malformed 2xx and other HTTP failures must
    # NOT cause a public-health fallback or guessed settings.
    user = update.effective_user
    data = await _backend_get(
        "/admin/status",
        headers=_admin_headers(user.id),
        distinguish_admin_denial=True,
    )
    if data is _ADMIN_STATUS_FORBIDDEN:
        health = await _backend_get("/health")
        if (
            not isinstance(health, dict)
            or "detail" in health
            or "error" in health
            or health.get("demo_only_mode") is not True
        ):
            await update.message.reply_text(unconfirmed)
            return
        await update.message.reply_text(
            "SignalGate settings:\n"
            "Demo only: True\n"
            "Split-ticket partial mode: ON (default)\n"
            "Default lot: 0.01  TP lots: 0.02/0.01/0.01"
        )
        return

    if (
        not isinstance(data, dict)
        or "detail" in data
        or "error" in data
        or data.get("demo_only_mode") is not True
        or not isinstance(data.get("settings"), dict)
    ):
        await update.message.reply_text(unconfirmed)
        return

    settings = data["settings"]
    if "detail" in settings or "error" in settings:
        await update.message.reply_text(unconfirmed)
        return

    def numeric_setting(key: str) -> Optional[str]:
        value = settings.get(key)
        if value is None:
            return "not set"
        if type(value) not in (str, int, float):
            return None
        shown = str(value)
        if len(shown) > 24 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", shown):
            return None
        return shown

    numeric_keys = (
        "default_signal_expiry_minutes", "default_lot_size",
        "tp1_lot", "tp2_lot", "tp3_lot",
        "tp1_close_percent", "tp2_close_percent", "tp3_close_percent",
    )
    values = {key: numeric_setting(key) for key in numeric_keys}
    split = settings.get("split_ticket_demo_partial_mode")
    if type(split) is bool:
        split_shown = str(split)
    elif type(split) is str and split.lower() in ("true", "false"):
        split_shown = split.lower()
    elif split is None:
        split_shown = "not set"
    else:
        split_shown = None
    if split_shown is None or any(value is None for value in values.values()):
        await update.message.reply_text(unconfirmed)
        return

    await update.message.reply_text(
        "\n".join((
            "SignalGate settings:",
            "Demo only: True",
            f"Expiry minutes: {values['default_signal_expiry_minutes']}",
            f"Split-ticket partial mode: {split_shown}",
            f"Default lot: {values['default_lot_size']}",
            f"TP lots: {values['tp1_lot']}/{values['tp2_lot']}/{values['tp3_lot']}",
            "Close %: "
            f"{values['tp1_close_percent']}/"
            f"{values['tp2_close_percent']}/{values['tp3_close_percent']}",
        ))
    )

async def provider_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Self-enrol a screenshot provider with a shared invite code (local demo only)."""
    if config.require_license:
        await update.message.reply_text(
            "Legacy /provider enrolment is disabled in hosted Provider Edition. "
            "Generate a feed-bound source token in the Provider Portal and use "
            "/connectprovider TOKEN."
        )
        return

    user = update.effective_user
    if config.is_signal_provider(user.id):
        await update.message.reply_text(
            "You are already a screenshot provider. Send a screenshot whenever ready."
        )
        return

    expected = config.provider_invite_code.strip()
    supplied = " ".join(context.args).strip() if context.args else ""
    if not expected:
        await update.message.reply_text(
            "Provider invite code is not configured yet. Ask Ben to set "
            "SIGNAL_PROVIDER_INVITE_CODE in .env and restart the bot."
        )
        return
    if supplied != expected:
        await update.message.reply_text("Invite code not recognised.")
        return

    config.add_local_provider(user.id)
    await update.message.reply_text(
        "SignalGate screenshot provider ready.\n\n"
        "Send me a signal screenshot. I will extract it, show you the details, "
        "and wait for Confirm before anything is sent."
    )


# --- callback (YES/NO) ----------------------------------------------------

async def on_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    # Telegram trade-card buttons are delivered to private subscriber chats.
    # Reject shared/inline or unknown-chat callbacks before reading identity,
    # parsing IDs or contacting the decision backend. An alert is visible only
    # to the clicker and leaves any shared card unchanged.
    if not _private_command_chat(update):
        await query.answer(
            text="Open a private chat with SignalGate to approve or reject a demo trade.",
            show_alert=True,
        )
        return
    await query.answer()
    user = query.from_user
    callback_data = query.data
    if not isinstance(callback_data, str):
        await query.edit_message_text("Invalid action.")
        return
    try:
        decision, signal_id = callback_data.split(":", 1)
    except ValueError:
        await query.edit_message_text("Invalid action.")
        return

    if decision not in {"YES", "NO"} or not _valid_signal_id(signal_id):
        await query.edit_message_text("Invalid action.")
        return
    path = (
        f"/signals/{signal_id}/approve"
        if decision == "YES"
        else f"/signals/{signal_id}/reject"
    )
    result = await _backend_post(
        path,
        json={"telegram_user_id": str(user.id)},
        headers=_registration_headers(),
    )
    # A response may be malformed even after the backend has committed YES/NO.
    # Only an allowlisted, typed result is safe for subscriber-facing text;
    # never reflect backend `message`, unknown codes or error-shaped 200s.
    code = result.get("result") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or "detail" in result
        or not isinstance(code, str)
        or code not in DECISION_ALLOWED_BY_ACTION[decision]
    ):
        await query.edit_message_text(
            "Decision could not be confirmed. Check the current trade state "
            "before retrying; the backend may already have processed it."
        )
        return

    await query.edit_message_text(
        f"{query.message.text}\n\n➡️ {DECISION_MESSAGES[code]}"
    )


# --- admin commands -------------------------------------------------------

def _require_admin(update: Update) -> bool:
    return config.is_admin(update.effective_user.id)


def _require_signal_provider(update: Update) -> bool:
    return config.is_signal_provider(update.effective_user.id)


def _role_name(telegram_user_id: int | str) -> str:
    if config.is_admin(telegram_user_id):
        return "admin"
    if not config.require_license and config.is_signal_provider(telegram_user_id):
        return "screenshot provider"
    return "tester"


async def screenshot_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Even the help path queries a user's provider-source status. Do not make
    # that tenant-linked lookup or expose its result from a shared chat.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /screenshothelp in a private chat with SignalGate. "
            "No provider source was checked."
        )
        return
    if not await _can_submit_provider_signal(update):
        await update.message.reply_text(
            "Screenshot submission requires a connected provider source.\n"
            "Generate a connection token in the Provider Portal, then send "
            "/connectprovider YOUR_TOKEN."
        )
        return
    await update.message.reply_text(
        "Screenshot workflow:\n"
        "1. Send me one chart/signal screenshot as a photo.\n"
        "2. I read symbol, BUY/SELL, entry, SL, TP1, TP2, TP3.\n"
        "3. Check every number carefully.\n"
        "4. Tap Confirm & Send only if it is correct.\n"
        "5. If anything is wrong, tap Edit and type the corrected signal.\n\n"
        "Nothing is sent to testers until you confirm."
    )


async def _create_and_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw_text: str,
    *,
    original_source_scope: Optional[Dict[str, str]] = None,
) -> str:
    """Create one tenant-bound signal and broadcast only to its feed subscribers."""
    if update.effective_chat is None or update.effective_message is None:
        return "Cannot identify Telegram source message. Nothing was sent."

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = str(update.effective_message.message_id)
    source = await _provider_source_status(user_id)

    # Recheck the exact preview binding immediately before signal creation.
    # A provider rebound from feed A to B may be ACTIVE but cannot submit A's
    # confirmed screenshot to B. The backend remains the final tenant authority.
    if original_source_scope is not None and (
        _source_scope(original_source_scope) is None
        or _source_scope(source) != _source_scope(original_source_scope)
    ):
        return (
            "Provider source changed since this screenshot preview. "
            "Nothing was submitted or sent; capture a new screenshot."
        )

    if source:
        signal = await _backend_post(
            "/provider-sources/telegram/signals",
            json={
                "telegram_user_id": str(user_id),
                "raw_text": raw_text,
                "source_message_id": f"{chat_id}:{message_id}",
                "expected_binding_id": source["binding_id"],
                "expected_provider_id": source["provider_id"],
                "expected_feed_id": source["feed_id"],
            },
            headers=_registration_headers(),
        )
        # The prior source status is never authoritative for the card expiry.
    else:
        # Local-demo legacy path only. Hosted mode requires the persisted,
        # feed-bound Telegram provider source above.
        if config.require_license or not config.is_signal_provider(user_id):
            return (
                "Provider source is not connected. Generate a token in the "
                "Provider Portal and send /connectprovider TOKEN."
            )
        signal = await _backend_post(
            "/signals/create",
            json={
                "raw_text": raw_text,
                "source": f"TELEGRAM_CHAT:{chat_id}",
                "source_message_id": message_id,
            },
            headers=_signal_provider_headers(user_id),
        )
        expiry = 5
        if config.is_admin(user_id):
            admin_status = await _backend_get(
                "/admin/status", headers=_admin_headers(user_id)
            )
            if admin_status and admin_status.get("settings"):
                try:
                    expiry = int(
                        admin_status["settings"].get(
                            "default_signal_expiry_minutes", 5
                        )
                    )
                except (TypeError, ValueError):
                    expiry = 5

    # A POST can have persisted a signal despite a malformed/failed response.
    # Never echo untrusted backend detail or parser_error (possibly credentials)
    # into Telegram; tell the provider to inspect history before retrying.
    uncertain = (
        "Signal submission could not be confirmed. Check provider history "
        "before retrying; no subscriber card was sent."
    )
    # A 200 with a `detail` field is error-shaped even when its value is
    # null/empty and the rest resembles a valid persisted signal. Never send
    # subscriber cards on contradictory creation receipts.
    if not isinstance(signal, dict) or "detail" in signal:
        return uncertain
    if signal.get("parser_status") != "VALID":
        return (
            "Parser did not accept this signal. Review the text and feed policy; "
            "no subscriber card was sent."
        )
    # Replay can return an existing, subsequently EXPIRED ledger row.
    # A VALID parse alone cannot authorise re-sending its old trade card.
    if signal.get("status") != "VALID":
        return (
            "Signal is not in a broadcastable state. No subscriber card was "
            "sent; check provider history."
        )
    if not _valid_signal_id(signal.get("id")):
        return uncertain

    # The original source binding and the persisted signal must describe the
    # same provider/feed. A rebind during signal creation cannot turn an older
    # source lookup into authority to broadcast a newer feed's signal.
    if source:
        expected_source = (
            f"FEED:{source['feed_id']}:TELEGRAM_BINDING:{source['binding_id']}"
        )
        if (
            signal.get("provider_id") != source["provider_id"]
            or signal.get("feed_id") != source["feed_id"]
            or signal.get("source") != expected_source
        ):
            return (
                "Signal creation was confirmed but its provider/feed binding "
                "changed. No subscriber card was sent; check provider history."
            )

    # A replay returns the same ledger row, but never a second authority to
    # submit subscriber cards. Missing or malformed creation proof fails closed.
    # After an ambiguous POST/send, reconcile with history; no blind resend.
    if source and signal.get("newly_created") is not True:
        return (
            "This source message was already recorded or its creation status "
            "could not be confirmed. No new subscriber card was sent; check "
            "provider history and subscriber delivery before any manual resend."
        )

    # The same HTTP 200 that confirmed persistence can contain malformed
    # presentation fields. Never broadcast a forged safety/price line.
    if not _safe_trade_card_signal(signal):
        return (
            "Signal card fields could not be confirmed. No subscriber card was "
            "sent; check provider history before retrying."
        )

    if source:
        expiry = _persisted_signal_expiry_minutes(signal)
        if expiry is None:
            return (
                "Signal expiry receipt could not be confirmed. No subscriber "
                "card was sent; check provider history before retrying."
            )

    from keyboards import format_trade_card, trade_card_keyboard

    card = format_trade_card(signal, expiry)
    keyboard = trade_card_keyboard(signal["id"])
    recipients = await _active_recipients(update, source, signal=signal)
    if recipients is None:
        return (
            "Signal was created but subscriber feed ownership could not be "
            "confirmed. No subscriber card was sent; check provider history."
        )
    sent = 0
    # A send_message exception can arrive after Telegram accepted the card.
    # Treat these as unknown outcomes, not proof of non-delivery.
    uncertain = 0
    for recipient_chat_id in recipients:
        # Recipient lookup and Telegram sends are awaited: the persisted
        # expiry can elapse after our pre-lookup check. Refuse to start each
        # subsequent hosted send once that original deadline has passed.
        if source and _persisted_signal_expiry_minutes(signal) is None:
            if uncertain:
                return (
                    f"Signal {signal['id']} created, but its expiry could no longer "
                    "be confirmed before further card delivery. "
                    f"Telegram accepted {sent} card submission(s); "
                    f"{uncertain} send attempt(s) have an unknown delivery outcome. "
                    "Further sends stopped. Check with subscribers before any resend."
                )
            return (
                f"Signal {signal['id']} created, but its expiry could no longer "
                f"be confirmed before further card delivery. Telegram accepted "
                f"{sent} card submission(s); further sends stopped. Delivery "
                "is not confirmed; check provider history before any manual resend."
            )
        try:
            await context.bot.send_message(
                chat_id=recipient_chat_id,
                text=card,
                reply_markup=keyboard,
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            uncertain += 1
            # Telegram transport exceptions can contain bot-token URLs and
            # recipient chat IDs. Log only the safe exception class.
            logger.warning("send card failed: %s", type(exc).__name__)
    if uncertain:
        return (
            f"Signal {signal['id']} created. Telegram accepted {sent} card "
            f"submission(s); {uncertain} send attempt(s) have unknown outcomes. "
            "An error does not prove non-delivery. Check with affected subscribers "
            "before any manual resend; no automatic retry was attempted."
        )
    return (
        f"Signal {signal['id']} created. Telegram accepted {sent} card "
        "submission(s); delivery is not confirmed."
    )


async def testsignal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # An administrator may also belong to public groups. Never parse or submit
    # group command text as a provider signal, or route cards from a shared chat.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /testsignal in a private chat with SignalGate. "
            "Nothing was submitted or sent."
        )
        return
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    raw_text = update.message.text.partition(" ")[2].strip()
    if not raw_text:
        await update.message.reply_text(
            "Usage: /testsignal XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"
        )
        return
    result = await _create_and_broadcast(update, context, raw_text)
    await update.message.reply_text(result)


# --- screenshot -> signal workflow ---------------------------------------
#
# The signal provider (admin) sends a chart screenshot. The backend extracts
# candidate text with a vision model and runs it through the deterministic
# parser. We PREVIEW the result and only broadcast after the provider taps
# Confirm. Nothing about extraction bypasses the parser or the human check.

# Match the backend's 5 MiB signal-image limit before requesting a Telegram
# download. Backend validates again; Telegram metadata alone is not authority.
MAX_SIGNAL_IMAGE_BYTES = 5 * 1024 * 1024


def _clear_pending_screenshot_preview(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "pending_signal_text", "awaiting_edit", "pending_preview_token",
        "pending_provider_source_scope", "active_screenshot_attempt",
    ):
        context.user_data.pop(key, None)


def _begin_screenshot_attempt(context: ContextTypes.DEFAULT_TYPE) -> str:
    # A later screenshot supersedes every earlier in-flight download/extraction.
    _clear_pending_screenshot_preview(context)
    attempt_token = secrets.token_hex(16)
    context.user_data["active_screenshot_attempt"] = attempt_token
    return attempt_token


def _is_current_screenshot_attempt(
    context: ContextTypes.DEFAULT_TYPE, attempt_token: str
) -> bool:
    current = context.user_data.get("active_screenshot_attempt")
    return (
        isinstance(current, str)
        and secrets.compare_digest(attempt_token, current)
    )


async def _reject_screenshot_size(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    size: int | None,
    attempt_token: str,
) -> bool:
    # A delayed older request must never clear or upload a newer screenshot.
    if not _is_current_screenshot_attempt(context, attempt_token):
        return True
    # Missing Telegram metadata is allowed only until the actual download size
    # is checked; malformed or oversized reported sizes fail closed immediately.
    if size is None:
        return False
    if type(size) is int and 0 <= size <= MAX_SIGNAL_IMAGE_BYTES:
        return False
    _clear_pending_screenshot_preview(context)
    await update.message.reply_text(
        "Screenshot size is invalid or exceeds 5 MiB; no preview was saved."
    )
    return True


async def _download_telegram_screenshot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    attempt_token: str,
) -> Optional[bytes]:
    """Contain Telegram file errors without logging bot-token-bearing exception text."""
    try:
        tg_file = await context.bot.get_file(file_id)
        # The resolved File may disagree with message metadata. Refuse before
        # allocating image bytes; only the current screenshot may change state.
        if await _reject_screenshot_size(
            update, context, tg_file.file_size, attempt_token
        ):
            return None
        downloaded = await tg_file.download_as_bytearray()
        if await _reject_screenshot_size(
            update, context, len(downloaded), attempt_token
        ):
            return None
        return bytes(downloaded)
    except Exception as exc:  # noqa: BLE001
        # Unhandled Telegram transport errors may contain full /bot<TOKEN>/
        # URLs. A late failed request must not erase a newer preview.
        if not _is_current_screenshot_attempt(context, attempt_token):
            return None
        _clear_pending_screenshot_preview(context)
        logger.warning("Telegram screenshot download failed: %s", type(exc).__name__)
        await update.message.reply_text(
            "Screenshot couldn't be retrieved. No preview was saved. Please try again."
        )
        return None


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Shared chats must not trigger provider lookup, image download or preview.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Send provider screenshots in a private chat with SignalGate. "
            "Nothing was downloaded or previewed here."
        )
        return
    attempt_token = _begin_screenshot_attempt(context)
    authorised = await _can_submit_provider_signal(update)
    if not _is_current_screenshot_attempt(context, attempt_token):
        return
    if not authorised:
        _clear_pending_screenshot_preview(context)
        await update.message.reply_text(
            "Connect this Telegram account to a provider feed with "
            "/connectprovider before submitting screenshots."
        )
        return

    # Refuse oversized metadata before any Telegram file download.
    photo = update.message.photo[-1]
    if await _reject_screenshot_size(update, context, photo.file_size, attempt_token):
        return
    await update.message.reply_text("📷 Reading your screenshot…")
    if not _is_current_screenshot_attempt(context, attempt_token):
        return
    image_bytes = await _download_telegram_screenshot(
        update, context, photo.file_id, attempt_token
    )
    if image_bytes is None:
        return
    await _preview_screenshot(
        update=update,
        context=context,
        image_bytes=image_bytes,
        mime="image/jpeg",
        attempt_token=attempt_token,
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Shared chats must not trigger provider lookup, image download or preview.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Send provider screenshots in a private chat with SignalGate. "
            "Nothing was downloaded or previewed here."
        )
        return
    attempt_token = _begin_screenshot_attempt(context)
    authorised = await _can_submit_provider_signal(update)
    if not _is_current_screenshot_attempt(context, attempt_token):
        return
    if not authorised:
        _clear_pending_screenshot_preview(context)
        await update.message.reply_text(
            "Connect this Telegram account to a provider feed with "
            "/connectprovider before submitting screenshots."
        )
        return

    document = update.message.document
    mime = document.mime_type or "application/octet-stream"
    if not mime.startswith("image/"):
        _clear_pending_screenshot_preview(context)
        await update.message.reply_text("Please send an image screenshot.")
        return

    if await _reject_screenshot_size(update, context, document.file_size, attempt_token):
        return
    await update.message.reply_text("📷 Reading your screenshot…")
    if not _is_current_screenshot_attempt(context, attempt_token):
        return
    image_bytes = await _download_telegram_screenshot(
        update, context, document.file_id, attempt_token
    )
    if image_bytes is None:
        return
    await _preview_screenshot(
        update=update,
        context=context,
        image_bytes=image_bytes,
        mime=mime,
        attempt_token=attempt_token,
    )


def _valid_screenshot_preview_payload(data: Any) -> bool:
    """Refuse malformed extractor JSON before preview formatting or pending state."""
    if not isinstance(data, dict):
        return False
    string_fields = (
        "extracted_text", "parser_status", "symbol", "direction", "entry_type",
        "confidence", "engine", "notes", "parser_error",
    )
    for field in string_fields:
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 2048):
            return False

    raw_text = data.get("extracted_text", "")
    if not isinstance(raw_text, str) or not isinstance(data.get("parser_status"), str):
        return False
    if data["parser_status"] == "VALID" and not raw_text.strip():
        return False

    for field in ("entry_price", "initial_stop_loss", "tp1", "tp2", "tp3"):
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            if not math.isfinite(value):
                return False
        except (OverflowError, ValueError):
            return False
    return True


async def _preview_screenshot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    mime: str,
    attempt_token: str | None = None,
) -> None:
    # Direct/offline callers preserve the earlier fresh-preview behaviour.
    # Telegram screenshot handlers supply the same token across awaits.
    if attempt_token is None:
        _clear_pending_screenshot_preview(context)
    elif not _is_current_screenshot_attempt(context, attempt_token):
        return
    user_id = update.effective_user.id
    source = await _provider_source_status(user_id)
    if attempt_token is not None and not _is_current_screenshot_attempt(
        context, attempt_token
    ):
        return
    if source:
        url = f"{config.backend_base_url}/provider-sources/telegram/extract"
        headers = _registration_headers()
        params = {"telegram_user_id": str(user_id)}
    else:
        if config.require_license:
            # The earlier photo permission check is not authority after a
            # source revocation or backend lookup failure.
            await update.message.reply_text(
                "Provider source is no longer connected. Nothing was extracted. "
                "Reconnect using a new token from the Provider Portal."
            )
            return
        # Local-demo legacy path only.
        url = f"{config.backend_base_url}/signals/extract"
        headers = _signal_provider_headers(user_id)
        params = None

    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(
                url,
                params=params,
                headers=headers,
                files={"file": ("signal", image_bytes, mime)},
            )
            if attempt_token is not None and not _is_current_screenshot_attempt(
                context, attempt_token
            ):
                return
            if resp.status_code != 200:
                # Backend error bodies may contain secrets or internal details.
                if attempt_token is not None:
                    _clear_pending_screenshot_preview(context)
                logger.warning("backend screenshot extraction returned HTTP %s", resp.status_code)
                await update.message.reply_text(
                    "Screenshot extraction was rejected by the backend. "
                    "No signal was created."
                )
                return
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        if attempt_token is not None:
            if not _is_current_screenshot_attempt(context, attempt_token):
                return
            _clear_pending_screenshot_preview(context)
        # HTTP exceptions can include credential-bearing URLs or response text.
        logger.warning("extract failed: %s", type(exc).__name__)
        await update.message.reply_text(
            "Couldn't read that image (backend/extractor error). Try again."
        )
        return

    # Treat extractor JSON as untrusted even on HTTP 200. A malformed response
    # must not crash callbacks or leave an earlier preview confirmable.
    if not _valid_screenshot_preview_payload(data):
        if attempt_token is not None:
            _clear_pending_screenshot_preview(context)
        logger.warning("backend screenshot extraction returned invalid preview shape")
        await update.message.reply_text(
            "Screenshot extraction returned an invalid response. Nothing was saved. "
            "Please try another screenshot."
        )
        return

    from keyboards import extract_preview_keyboard, format_extraction_preview

    try:
        preview = format_extraction_preview(data)
        # Telegram counts UTF-16 code units rather than Python codepoints.
        # Also reject invalid Unicode in an otherwise well-typed JSON string.
        preview_length = len(preview.encode("utf-16-le")) // 2
        preview.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError):
        if attempt_token is not None:
            _clear_pending_screenshot_preview(context)
        logger.warning("backend screenshot extraction returned unrenderable preview")
        await update.message.reply_text(
            "Screenshot preview could not be rendered. Nothing was saved. "
            "Please try another screenshot."
        )
        return
    if preview_length > 3900:
        if attempt_token is not None:
            _clear_pending_screenshot_preview(context)
        logger.warning("backend screenshot extraction preview exceeded display limit")
        await update.message.reply_text(
            "Screenshot preview was too long. Nothing was saved. "
            "Please try a clearer screenshot."
        )
        return

    # An older extraction may complete after a newer screenshot was started.
    # Never let it overwrite the new preview or issue a confirmable callback.
    if attempt_token is not None:
        if not _is_current_screenshot_attempt(context, attempt_token):
            return
        context.user_data.pop("active_screenshot_attempt", None)
    preview_token = secrets.token_hex(8)
    # An old A preview must not become a B signal if Telegram identity is
    # rebound between extraction and the provider's Confirm/Edit action.
    scope = _source_scope(source)
    if scope is not None:
        context.user_data["pending_provider_source_scope"] = scope
    context.user_data["pending_signal_text"] = data.get("extracted_text", "")
    context.user_data["pending_preview_token"] = preview_token
    await update.message.reply_text(
        preview,
        reply_markup=extract_preview_keyboard(
            data.get("parser_status") == "VALID", preview_token
        ),
    )


async def on_signal_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Confirm / Edit / Cancel on an extracted-signal preview."""
    query = update.callback_query
    # A callback can survive after a private screenshot preview, then arrive
    # from a shared chat. Do not inspect or edit a group message or touch the
    # private candidate: notify only the clicker through an ephemeral alert.
    if not _private_command_chat(update):
        await query.answer(
            text=(
                "Screenshot confirmation and edits require a private chat with "
                "SignalGate. Nothing was sent."
            ),
            show_alert=True,
        )
        return
    await query.answer()
    callback_data = query.data if isinstance(query.data, str) else ""
    action, separator, token = callback_data.partition(":")
    active_token = context.user_data.get("pending_preview_token")
    if (
        separator != ":"
        or not isinstance(active_token, str)
        or not secrets.compare_digest(token, active_token)
    ):
        # An old button cannot confirm/edit/cancel a newer candidate.
        await query.edit_message_text(
            "This screenshot preview has expired. Nothing was sent."
        )
        return
    original_scope = context.user_data.get("pending_provider_source_scope")
    if isinstance(original_scope, dict):
        original_scope = dict(original_scope)
    authorised = await _preview_source_authorised(update, original_scope)
    # Permission lookup awaits HTTP: a later screenshot or cancellation could
    # supersede this callback. Scope as well as nonce must remain unchanged.
    refreshed_token = context.user_data.get("pending_preview_token")
    if (
        not isinstance(refreshed_token, str)
        or not secrets.compare_digest(token, refreshed_token)
        or original_scope != context.user_data.get("pending_provider_source_scope")
    ):
        await query.edit_message_text(
            "This screenshot preview has expired. Nothing was sent."
        )
        return
    if not authorised:
        _clear_pending_screenshot_preview(context)
        await query.edit_message_text(
            "Provider source changed or is no longer connected. Nothing was sent."
        )
        return

    if action == "SIGNO":
        _clear_pending_screenshot_preview(context)
        await query.edit_message_text("❌ Cancelled. Nothing was sent.")
        return

    if action == "SIGEDIT":
        context.user_data["awaiting_edit"] = True
        current = context.user_data.get("pending_signal_text", "")
        await query.edit_message_text(
            "✏️ Send the corrected signal as text, e.g.\n"
            "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363\n\n"
            f"(I read: “{current}”)"
        )
        return

    if action == "SIGOK":
        candidate = context.user_data.get("pending_signal_text")
        raw_text = candidate.strip() if isinstance(candidate, str) else ""
        if not raw_text:
            _clear_pending_screenshot_preview(context)
            await query.edit_message_text(
                "Nothing to send — I couldn't read any text. Tap Edit next time."
            )
            return
        # Consume the preview before awaiting I/O: a second tap cannot reuse it.
        _clear_pending_screenshot_preview(context)
        result = await _create_and_broadcast(
            update, context, raw_text, original_source_scope=original_scope
        )
        await query.edit_message_text(f"{query.message.text}\n\n➡️ {result}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text handler. Only acts when the admin is editing an extracted signal."""
    if not context.user_data.get("awaiting_edit"):
        return  # ignore ordinary chatter
    # Telegram user_data persists across chats. Do not let a shared-chat text
    # consume or overwrite a private screenshot's pending correction.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Screenshot corrections require a private chat with SignalGate. "
            "Nothing was sent."
        )
        return
    # Bind corrected text to its exact preview and source across the async
    # permission check. A newer screenshot/rebind/Cancel cannot reuse it.
    edit_token = context.user_data.get("pending_preview_token")
    if (
        not isinstance(edit_token, str)
        or len(edit_token) != 16
        or any(ch not in "0123456789abcdef" for ch in edit_token)
    ):
        _clear_pending_screenshot_preview(context)
        return
    original_scope = context.user_data.get("pending_provider_source_scope")
    if isinstance(original_scope, dict):
        original_scope = dict(original_scope)
    authorised = await _preview_source_authorised(update, original_scope)
    refreshed = context.user_data.get("pending_preview_token")
    if (
        not context.user_data.get("awaiting_edit")
        or not isinstance(refreshed, str)
        or len(refreshed) != 16
        or any(ch not in "0123456789abcdef" for ch in refreshed)
        or not secrets.compare_digest(edit_token, refreshed)
        or original_scope != context.user_data.get("pending_provider_source_scope")
    ):
        return  # An obsolete edit must never act on a newer preview.
    if not authorised:
        _clear_pending_screenshot_preview(context)
        return
    raw_text = (update.message.text or "").strip()
    if not raw_text:
        await update.message.reply_text("Empty — send the corrected signal text.")
        return
    _clear_pending_screenshot_preview(context)
    result = await _create_and_broadcast(
        update, context, raw_text, original_source_scope=original_scope
    )
    await update.message.reply_text(result)


async def _active_recipients(
    update: Update,
    source: Optional[Dict[str, Any]] = None,
    signal: Optional[Dict[str, Any]] = None,
) -> Optional[List[str]]:
    """Fail closed if recipient ownership differs from the persisted signal."""
    if source:
        if not isinstance(signal, dict) or any(
            signal.get(field) != source.get(field)
            for field in ("provider_id", "feed_id")
        ):
            return None
        data = await _backend_get(
            "/provider-sources/telegram/recipients",
            params={"telegram_user_id": str(update.effective_user.id)},
            headers=_registration_headers(),
        )
        if (
            not isinstance(data, dict)
            or "detail" in data
            or any(
                data.get(field) != source.get(field)
                for field in ("binding_id", "provider_id", "feed_id")
            )
        ):
            # An error-shaped HTTP 200 is not a recipient authorisation even
            # when it echoes matching identifiers. Rebinds also fail closed.
            return None
        recipients: set[str] = set()
    else:
        # Local-demo compatibility only; hosted sources use the scoped receipt.
        data = await _backend_get(
            "/signals/recipients",
            headers=_signal_provider_headers(update.effective_user.id),
        )
        recipients = {str(update.effective_chat.id)}
        if data is None:
            return list(recipients)

    if not isinstance(data, dict) or not isinstance(data.get("recipients"), list):
        return None
    for recipient in data["recipients"]:
        if not isinstance(recipient, dict):
            return None
        telegram_id = recipient.get("telegram_user_id")
        # Subscriber identities are positive Telegram *user* IDs, not negative
        # group/channel chat IDs. Refuse noncanonical or out-of-range values
        # before delivering to any recipient in this response.
        if (
            not isinstance(telegram_id, str)
            or not telegram_id.isascii()
            or not telegram_id.isdecimal()
            or telegram_id.startswith("0")
            or len(telegram_id) > 16
            or int(telegram_id) > (1 << 52) - 1
        ):
            return None
        recipients.add(telegram_id)
    return list(recipients)


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    result = await _backend_post(
        "/admin/pause", headers=_admin_headers(update.effective_user.id)
    )
    # A successful HTTP response alone is not proof the emergency stop took
    # effect. A failed response can also arrive AFTER the backend commits it.
    # Do not automatically retry or claim a confirmed pause on uncertainty.
    confirmed = (
        isinstance(result, dict)
        and set(result) == {"status", "admin_paused"}
        and result.get("status") == "ok"
        and result.get("admin_paused") is True
    )
    await update.message.reply_text(
        "Trading paused."
        if confirmed
        else (
            "Pause status unconfirmed. Verify the administrator pause state "
            "before relying on this response; the backend may have processed it."
        )
    )


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Resuming lifts a protective pause. Never let shared/unknown Telegram
    # chats submit the state-changing request or consult admin credentials.
    # Do not restrict /pause here: it is a separate emergency-stop control.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /resume in a private chat with SignalGate. "
            "No resume request was submitted."
        )
        return
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    result = await _backend_post(
        "/admin/resume", headers=_admin_headers(update.effective_user.id)
    )
    # A 2xx response may be malformed or error-shaped even when the backend
    # already changed the administrative state. Never claim a successful resume
    # without the exact typed receipt returned by /admin/resume.
    confirmed = (
        isinstance(result, dict)
        and set(result) == {"status", "admin_paused"}
        and result.get("status") == "ok"
        and result.get("admin_paused") is False
    )
    await update.message.reply_text(
        "Trading resumed."
        if confirmed
        else (
            "Resume status unconfirmed. Verify the administrator pause state "
            "before relying on this response; the backend may have processed it."
        )
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Administrative user counts must never be requested from a shared chat.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /users in a private chat with SignalGate. "
            "No user statistics were retrieved."
        )
        return
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    data = await _backend_get(
        "/admin/status", headers=_admin_headers(update.effective_user.id)
    )
    # A successful HTTP status does not establish a trustworthy admin count.
    # SQL COUNT() is a nonnegative signed 64-bit integer; bool is not a count.
    counts = data.get("counts") if isinstance(data, dict) and not (
        "detail" in data or "error" in data
    ) else None
    users = counts.get("users") if isinstance(counts, dict) else None
    if type(users) is not int or not 0 <= users <= (1 << 63) - 1:
        await update.message.reply_text(
            "User statistics could not be confirmed. Verify the "
            "administrative count before relying on it."
        )
        return
    await update.message.reply_text(f"Active user count (approx): {users}")


async def lastsignals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Signal history belongs in the administrator's private chat, never in a
    # shared conversation where its contents and identity may be forwarded.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /lastsignals in a private chat with SignalGate. "
            "No signal history was retrieved."
        )
        return
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    signals = await _backend_get(
        "/signals/recent", headers=_admin_headers(update.effective_user.id)
    )
    # A successful HTTP status alone does not make signal history trustworthy.
    # Render only the first ten fully validated rows; malformed/error-shaped
    # responses must not crash the handler or reflect untrusted diagnostics.
    if signals is None or signals == []:
        await update.message.reply_text("No signals or backend unreachable.")
        return

    def safe_history_text(value: Any, *, required: bool) -> bool:
        if value is None:
            return not required
        return (
            type(value) is str
            and (not required or bool(value))
            and len(value) <= 64
            and value.isascii()
            and value.isprintable()
        )

    def safe_history_row(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and "detail" not in row
            and "error" not in row
            and all(
                safe_history_text(row.get(field), required=True)
                for field in ("id", "parser_status", "status")
            )
            and all(
                safe_history_text(row.get(field), required=False)
                for field in ("symbol", "direction")
            )
        )

    recent = signals[:10] if isinstance(signals, list) else []
    if not recent or not all(safe_history_row(row) for row in recent):
        await update.message.reply_text(
            "Signal history could not be confirmed. Verify the backend "
            "before relying on its records."
        )
        return
    lines = ["Recent signals:"]
    for s in recent:
        lines.append(
            f"{s['id']}: {s.get('symbol')} {s.get('direction')} "
            f"[{s['parser_status']}] {s['status']}"
        )
    await update.message.reply_text("\n".join(lines))


async def lastcommands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Command/execution counts are operational metadata, not group-chat output.
    # Refuse before admin identity or any backend credential/request is consulted.
    if not _private_command_chat(update):
        await update.message.reply_text(
            "Use /lastcommands in a private chat with SignalGate. "
            "No command statistics were retrieved."
        )
        return
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    data = await _backend_get(
        "/admin/status", headers=_admin_headers(update.effective_user.id)
    )
    # HTTP 200 alone does not establish trustworthy operational statistics.
    # The backend returns SQL COUNT() values: actual nonnegative int64s.
    # Refuse error-shaped and partial receipts instead of displaying None,
    # booleans, impossible values or server-provided diagnostics.
    counts = data.get("counts") if isinstance(data, dict) and not (
        "detail" in data or "error" in data
    ) else None
    fields = ("commands", "executions", "management_events")
    values = tuple(counts.get(name) for name in fields) if isinstance(counts, dict) else ()
    if len(values) != len(fields) or not all(
        type(value) is int and 0 <= value <= (1 << 63) - 1 for value in values
    ):
        await update.message.reply_text(
            "Command statistics could not be confirmed. Verify the "
            "administrative counts before relying on them."
        )
        return
    commands, executions, management_events = values
    await update.message.reply_text(
        f"Command count: {commands}\n"
        f"Executions: {executions}\n"
        f"Management events: {management_events}"
    )
