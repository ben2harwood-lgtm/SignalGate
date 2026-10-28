"""Telegram command and callback handlers.

The bot is a thin client over the backend HTTP API. It performs NO trading
logic itself — all decisions, idempotency and safety live in the backend.
"""
from __future__ import annotations

import logging
import math
import secrets
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
}


# --- backend helpers ------------------------------------------------------

async def _backend_get(path: str, **kwargs) -> Optional[Any]:
    url = f"{config.backend_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(url, **kwargs)
            if not 200 <= resp.status_code < 300:
                logger.warning("backend GET %s returned HTTP %s", path, resp.status_code)
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
    if not data or data.get("detail"):
        return None
    return data


async def _can_submit_provider_signal(update: Update) -> bool:
    if await _provider_source_status(update.effective_user.id):
        return True
    if config.require_license:
        return False
    # Local-demo backwards compatibility only.
    return config.is_signal_provider(update.effective_user.id)


# --- user commands --------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    source = await _provider_source_status(user.id)
    if source:
        provider_name = (
            source.get("provider_display_name")
            or source.get("provider_name")
            or "provider"
        )
        await update.message.reply_text(
            f"SignalGate provider source connected to {provider_name} — "
            f"{source.get('feed_name', 'feed')}.\n"
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
        if registration is None:
            await update.message.reply_text(
                "SignalGate backend is unreachable. Registration was not confirmed."
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
    if registration is None or registration.get("detail"):
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
        await update.message.reply_text(
            "SignalGate backend is unreachable. The invite was not confirmed."
        )
        return
    if result.get("detail"):
        await update.message.reply_text(
            f"Invite not accepted: {result.get('detail')}"
        )
        return

    provider_name = (
        result.get("provider_display_name")
        or result.get("provider_name")
        or "the provider"
    )
    message = (
        f"Joined {provider_name} — {result.get('feed_name', 'feed')}.\n"
        "You will only receive cards for feeds you have explicitly joined.\n"
        "Demo mode only. No live trades."
    )
    license_key = registration.get("license_key")
    if license_key:
        message += (
            "\n\nYour one-time EA licence is:\n"
            f"{license_key}\n"
            "Keep it private. SignalGate cannot display it again; "
            "if it is lost, an admin must rotate it."
        )
    await update.message.reply_text(message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    health = await _backend_get("/health")
    source = await _provider_source_status(user.id)

    backend_ok = health is not None
    paused = health.get("admin_paused") if health else "unknown"
    role = _role_name(user.id)
    if source:
        role = "provider source"
    lines = [
        f"Registered: yes (telegram id {user.id})",
        f"Role: {role}",
        f"Backend reachable: {'yes' if backend_ok else 'no'}",
        f"Demo only mode: {health.get('demo_only_mode') if health else 'unknown'}",
        f"Admin paused: {paused}",
    ]
    if source:
        lines.extend(
            [
                f"Provider: {source.get('provider_display_name') or source.get('provider_name')}",
                f"Feed: {source.get('feed_name')} ({source.get('feed_id')})",
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
    if result is None:
        await update.message.reply_text(
            "SignalGate backend is unreachable. Provider source was not connected."
        )
        return
    if result.get("detail"):
        # Backend diagnostics can contain token text or server internals.
        # Never echo an arbitrary error detail to a Telegram conversation.
        await update.message.reply_text(
            "Provider source not connected. The token may be invalid, expired, "
            "or already used. Generate a new feed-bound token in the Provider Portal."
        )
        return
    provider_name = (
        result.get("provider_display_name")
        or result.get("provider_name")
        or "provider"
    )
    await update.message.reply_text(
        f"Provider source connected to {provider_name} — "
        f"{result.get('feed_name', 'feed')}.\n"
        "Send /screenshothelp or send a signal screenshot when ready.\n"
        "Demo mode only."
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Admin status endpoint returns settings; non-admins get the generic view.
    user = update.effective_user
    data = await _backend_get("/admin/status", headers=_admin_headers(user.id))
    if data and "settings" in data:
        s = data["settings"]
        lines = [
            "SignalGate settings:",
            f"Demo only: {data.get('demo_only_mode')}",
            f"Expiry minutes: {s.get('default_signal_expiry_minutes')}",
            f"Split-ticket partial mode: {s.get('split_ticket_demo_partial_mode')}",
            f"Default lot: {s.get('default_lot_size')}",
            f"TP lots: {s.get('tp1_lot')}/{s.get('tp2_lot')}/{s.get('tp3_lot')}",
            f"Close %: {s.get('tp1_close_percent')}/"
            f"{s.get('tp2_close_percent')}/{s.get('tp3_close_percent')}",
        ]
    else:
        health = await _backend_get("/health")
        lines = [
            "SignalGate settings:",
            f"Demo only: {health.get('demo_only_mode') if health else 'unknown'}",
            "Split-ticket partial mode: ON (default)",
            "Default lot: 0.01  TP lots: 0.02/0.01/0.01",
        ]
    await update.message.reply_text("\n".join(lines))


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
    await query.answer()
    user = query.from_user
    try:
        decision, signal_id = query.data.split(":", 1)
    except ValueError:
        await query.edit_message_text("Invalid action.")
        return

    if decision not in {"YES", "NO"} or not signal_id:
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
    if not isinstance(result, dict) or not result.get("result"):
        await query.edit_message_text(
            "Decision could not be confirmed. Check the current trade state "
            "before retrying; the backend may already have processed it."
        )
        return

    code = result.get("result", "")
    message = DECISION_MESSAGES.get(code, result.get("message", code))
    await query.edit_message_text(f"{query.message.text}\n\n➡️ {message}")


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
    update: Update, context: ContextTypes.DEFAULT_TYPE, raw_text: str
) -> str:
    """Create one tenant-bound signal and broadcast only to its feed subscribers."""
    if update.effective_chat is None or update.effective_message is None:
        return "Cannot identify Telegram source message. Nothing was sent."

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = str(update.effective_message.message_id)
    source = await _provider_source_status(user_id)

    if source:
        signal = await _backend_post(
            "/provider-sources/telegram/signals",
            json={
                "telegram_user_id": str(user_id),
                "raw_text": raw_text,
                "source_message_id": f"{chat_id}:{message_id}",
            },
            headers=_registration_headers(),
        )
        try:
            expiry = int(source.get("expiry_minutes") or 5)
        except (TypeError, ValueError):
            expiry = 5
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

    if signal is None:
        return "Backend unreachable."
    if signal.get("detail"):
        return f"Signal not created: {signal.get('detail')}"
    if signal.get("parser_status") != "VALID":
        return f"Parser rejected signal: {signal.get('parser_error')}"

    from keyboards import format_trade_card, trade_card_keyboard

    card = format_trade_card(signal, expiry)
    keyboard = trade_card_keyboard(signal["id"])
    recipients = await _active_recipients(update, source)
    sent = 0
    for recipient_chat_id in recipients:
        try:
            await context.bot.send_message(
                chat_id=recipient_chat_id,
                text=card,
                reply_markup=keyboard,
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            # Telegram transport exceptions can contain bot-token URLs and
            # recipient chat IDs. Log only the safe exception class.
            logger.warning("send card failed: %s", type(exc).__name__)
    return f"Signal {signal['id']} created and card sent to {sent} subscriber(s)."


async def testsignal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        "active_screenshot_attempt",
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
    authorised = await _can_submit_provider_signal(update)
    # The permission lookup awaits HTTP. Another screenshot can supersede this
    # preview while it is suspended: check the nonce again after the await.
    refreshed_token = context.user_data.get("pending_preview_token")
    if (
        not isinstance(refreshed_token, str)
        or not secrets.compare_digest(token, refreshed_token)
    ):
        await query.edit_message_text(
            "This screenshot preview has expired. Nothing was sent."
        )
        return
    if not authorised:
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("awaiting_edit", None)
        context.user_data.pop("pending_preview_token", None)
        await query.edit_message_text(
            "Provider source is no longer connected. Nothing was sent."
        )
        return

    if action == "SIGNO":
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("awaiting_edit", None)
        context.user_data.pop("pending_preview_token", None)
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
            context.user_data.pop("pending_signal_text", None)
            context.user_data.pop("awaiting_edit", None)
            context.user_data.pop("pending_preview_token", None)
            await query.edit_message_text(
                "Nothing to send — I couldn't read any text. Tap Edit next time."
            )
            return
        # Consume the preview before awaiting I/O: a second tap cannot reuse it.
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("awaiting_edit", None)
        context.user_data.pop("pending_preview_token", None)
        result = await _create_and_broadcast(update, context, raw_text)
        await query.edit_message_text(f"{query.message.text}\n\n➡️ {result}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text handler. Only acts when the admin is editing an extracted signal."""
    if not context.user_data.get("awaiting_edit"):
        return  # ignore ordinary chatter
    # Bind corrected text to its exact preview across the async permission check.
    # A newer screenshot/cancel or another edit can consume it while I/O awaits.
    edit_token = context.user_data.get("pending_preview_token")
    if (
        not isinstance(edit_token, str)
        or len(edit_token) != 16
        or any(ch not in "0123456789abcdef" for ch in edit_token)
    ):
        context.user_data.pop("awaiting_edit", None)
        return
    authorised = await _can_submit_provider_signal(update)
    refreshed = context.user_data.get("pending_preview_token")
    if (
        not context.user_data.get("awaiting_edit")
        or not isinstance(refreshed, str)
        or len(refreshed) != 16
        or any(ch not in "0123456789abcdef" for ch in refreshed)
        or not secrets.compare_digest(edit_token, refreshed)
    ):
        return  # An obsolete edit must never act on a newer preview.
    if not authorised:
        context.user_data.pop("awaiting_edit", None)
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("pending_preview_token", None)
        return
    raw_text = (update.message.text or "").strip()
    if not raw_text:
        await update.message.reply_text("Empty — send the corrected signal text.")
        return
    context.user_data.pop("awaiting_edit", None)
    context.user_data.pop("pending_signal_text", None)
    context.user_data.pop("pending_preview_token", None)
    result = await _create_and_broadcast(update, context, raw_text)
    await update.message.reply_text(result)


async def _active_recipients(
    update: Update,
    source: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return only eligible recipients for the provider source/feed."""
    if source:
        data = await _backend_get(
            "/provider-sources/telegram/recipients",
            params={"telegram_user_id": str(update.effective_user.id)},
            headers=_registration_headers(),
        )
        recipients: set[str] = set()
    else:
        # Legacy local-demo behaviour includes the submitting provider chat.
        data = await _backend_get(
            "/signals/recipients",
            headers=_signal_provider_headers(update.effective_user.id),
        )
        recipients = {str(update.effective_chat.id)}

    if data and data.get("recipients"):
        for recipient in data["recipients"]:
            telegram_id = recipient.get("telegram_user_id")
            if telegram_id:
                recipients.add(str(telegram_id))
    return list(recipients)


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    result = await _backend_post(
        "/admin/pause", headers=_admin_headers(update.effective_user.id)
    )
    await update.message.reply_text(
        "Trading paused." if result else "Backend unreachable."
    )


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    result = await _backend_post(
        "/admin/resume", headers=_admin_headers(update.effective_user.id)
    )
    await update.message.reply_text(
        "Trading resumed." if result else "Backend unreachable."
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    data = await _backend_get(
        "/admin/status", headers=_admin_headers(update.effective_user.id)
    )
    if not data:
        await update.message.reply_text("Backend unreachable.")
        return
    await update.message.reply_text(
        f"Active user count (approx): {data['counts'].get('users')}"
    )


async def lastsignals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    signals = await _backend_get(
        "/signals/recent", headers=_admin_headers(update.effective_user.id)
    )
    if not signals:
        await update.message.reply_text("No signals or backend unreachable.")
        return
    lines = ["Recent signals:"]
    for s in signals[:10]:
        lines.append(
            f"{s['id']}: {s.get('symbol')} {s.get('direction')} "
            f"[{s['parser_status']}] {s['status']}"
        )
    await update.message.reply_text("\n".join(lines))


async def lastcommands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_admin(update):
        await update.message.reply_text("Admin only.")
        return
    data = await _backend_get(
        "/admin/status", headers=_admin_headers(update.effective_user.id)
    )
    if not data:
        await update.message.reply_text("Backend unreachable.")
        return
    await update.message.reply_text(
        f"Command count: {data['counts'].get('commands')}\n"
        f"Executions: {data['counts'].get('executions')}\n"
        f"Management events: {data['counts'].get('management_events')}"
    )
