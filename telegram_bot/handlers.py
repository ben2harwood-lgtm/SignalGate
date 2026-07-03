"""Telegram command and callback handlers.

The bot is a thin client over the backend HTTP API. It performs NO trading
logic itself — all decisions, idempotency and safety live in the backend.
"""
from __future__ import annotations

import logging
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
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("backend GET %s failed: %s", path, exc)
        return None


async def _backend_post(path: str, **kwargs) -> Optional[Any]:
    url = f"{config.backend_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(url, **kwargs)
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("backend POST %s failed: %s", path, exc)
        return None


def _admin_headers(user_id: int) -> Dict[str, str]:
    return {"X-Admin-Id": str(user_id)}


def _signal_provider_headers(user_id: int) -> Dict[str, str]:
    # If the bot has verified a provider locally (via invite code), let the bot
    # call provider-only backend actions with the configured admin header. The
    # provider never sees this header; it just avoids an env edit + restart.
    admin_id = config.first_admin_id()
    if admin_id:
        return {"X-Admin-Id": admin_id}
    return {"X-Signal-Provider-Id": str(user_id)}


# --- user commands --------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    # ALWAYS register (idempotent create-or-update). Previously admins and
    # signal providers skipped registration entirely, so tapping YES on a trade
    # card looped forever on "You are not registered. Send /start first."
    result = await _backend_post(
        "/register_user",
        json={
            "telegram_user_id": str(user.id),
            "telegram_username": user.username,
            "first_name": user.first_name,
        },
    )
    if not result or "id" not in result:
        # Don't claim success when the backend is unreachable (the old bug hid
        # this until the YES tap failed with USER_NOT_FOUND).
        await update.message.reply_text(
            "Could not reach the SignalGate backend to register you.\n"
            "Make sure the backend is running (Start Backend), then send "
            "/start again."
        )
        return

    backend_user_id = result["id"]
    lines = [
        "SignalGate demo tester registered.",
        "Demo mode only. No live trades.",
        "",
        f"Your backend user id: {backend_user_id}",
        "Put this in the EA's UserID input when you set up MetaTrader.",
    ]
    if config.is_signal_provider(user.id):
        lines += [
            "",
            "You are also a screenshot provider. Send me a signal screenshot and "
            "I will read it, show the extracted SL/TP details, and wait for your "
            "Confirm before anything is sent.",
        ]
    await update.message.reply_text("\n".join(lines))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    health = await _backend_get("/health")
    backend_ok = health is not None
    paused = health.get("admin_paused") if health else "unknown"

    # Ask the backend whether this user is actually registered instead of
    # hardcoding "yes" (which lied when registration had failed).
    me = await _backend_get(f"/users/{user.id}")
    registered = bool(me and me.get("id"))

    lines = [f"Registered: {'yes' if registered else 'no — send /start'}"]
    if registered:
        lines.append(f"Your backend user id: {me['id']} (use as EA UserID)")
        lines.append(f"Account status: {me.get('status')}")
    lines += [
        f"Telegram id: {user.id}",
        f"Role: {_role_name(user.id)}",
        f"Backend reachable: {'yes' if backend_ok else 'no'}",
        f"Demo only mode: {health.get('demo_only_mode') if health else 'unknown'}",
        f"Admin paused: {paused}",
    ]
    await update.message.reply_text("\n".join(lines))


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
    """Self-enrol a screenshot provider with a shared invite code."""
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

    path = (
        f"/signals/{signal_id}/approve"
        if decision == "YES"
        else f"/signals/{signal_id}/reject"
    )
    result = await _backend_post(path, json={"telegram_user_id": str(user.id)})
    if result is None:
        await query.edit_message_text("Backend unreachable. Try again.")
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
    if config.is_signal_provider(telegram_user_id):
        return "screenshot provider"
    return "tester"


async def screenshot_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_signal_provider(update):
        await update.message.reply_text(
            "Screenshot submission is limited to approved signal providers.\n"
            "If Ben gave you an invite code, send /provider YOUR_CODE."
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
    """Create a signal from confirmed text and broadcast the trade card.

    Shared by /testsignal and the screenshot-confirmation flow. Returns a
    human-readable status string. The backend's deterministic parser still has
    the final say on validity.
    """
    signal = await _backend_post(
        "/signals/create",
        json={"raw_text": raw_text},
        headers=_signal_provider_headers(update.effective_user.id),
    )
    if signal is None:
        return "Backend unreachable."
    if signal.get("parser_status") != "VALID":
        return f"Parser rejected signal: {signal.get('parser_error')}"

    from keyboards import format_trade_card, trade_card_keyboard

    status = await _backend_get(
        "/admin/status", headers=_admin_headers(update.effective_user.id)
    )
    expiry = 5
    if status and status.get("settings"):
        try:
            expiry = int(status["settings"].get("default_signal_expiry_minutes", 5))
        except (TypeError, ValueError):
            expiry = 5

    card = format_trade_card(signal, expiry)
    keyboard = trade_card_keyboard(signal["id"])

    recipients = await _active_recipients(update)
    sent = 0
    for chat_id in recipients:
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=card, reply_markup=keyboard
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("send card to %s failed: %s", chat_id, exc)
    return f"Signal {signal['id']} created and card sent to {sent} tester(s)."


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

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_signal_provider(update):
        await update.message.reply_text(
            "Only the signal provider can submit screenshots."
        )
        return

    await update.message.reply_text("📷 Reading your screenshot…")

    # Download the highest-resolution version of the photo.
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    await _preview_screenshot(
        update=update,
        context=context,
        image_bytes=image_bytes,
        mime="image/jpeg",
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _require_signal_provider(update):
        await update.message.reply_text(
            "Only the signal provider can submit screenshots."
        )
        return

    document = update.message.document
    mime = document.mime_type or "application/octet-stream"
    if not mime.startswith("image/"):
        await update.message.reply_text("Please send an image screenshot.")
        return

    await update.message.reply_text("📷 Reading your screenshot…")
    tg_file = await context.bot.get_file(document.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())
    await _preview_screenshot(
        update=update,
        context=context,
        image_bytes=image_bytes,
        mime=mime,
    )


async def _preview_screenshot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    mime: str,
) -> None:
    url = f"{config.backend_base_url}/signals/extract"
    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(
                url,
                headers=_signal_provider_headers(update.effective_user.id),
                files={"file": ("signal", image_bytes, mime)},
            )
            if resp.status_code != 200:
                await update.message.reply_text(
                    f"Screenshot rejected by backend: {resp.text}"
                )
                return
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract failed: %s", exc)
        await update.message.reply_text(
            "Couldn't read that image (backend/extractor error). Try again, or "
            "type the signal with /testsignal."
        )
        return

    # Hold the candidate text in per-user state until Confirm/Edit/Cancel.
    context.user_data["pending_signal_text"] = data.get("extracted_text", "")
    context.user_data.pop("awaiting_edit", None)

    from keyboards import extract_preview_keyboard, format_extraction_preview

    await update.message.reply_text(
        format_extraction_preview(data),
        reply_markup=extract_preview_keyboard(data.get("parser_status") == "VALID"),
    )


async def on_signal_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Confirm / Edit / Cancel on an extracted-signal preview."""
    query = update.callback_query
    await query.answer()
    if not _require_signal_provider(update):
        await query.edit_message_text("Signal provider only.")
        return

    action = query.data
    if action == "SIGNO":
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("awaiting_edit", None)
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
        raw_text = context.user_data.get("pending_signal_text", "").strip()
        if not raw_text:
            await query.edit_message_text(
                "Nothing to send — I couldn't read any text. Tap Edit next time."
            )
            return
        result = await _create_and_broadcast(update, context, raw_text)
        context.user_data.pop("pending_signal_text", None)
        context.user_data.pop("awaiting_edit", None)
        await query.edit_message_text(f"{query.message.text}\n\n➡️ {result}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text handler. Only acts when the admin is editing an extracted signal."""
    if not context.user_data.get("awaiting_edit"):
        return  # ignore ordinary chatter
    if not _require_signal_provider(update):
        return
    raw_text = (update.message.text or "").strip()
    if not raw_text:
        await update.message.reply_text("Empty — send the corrected signal text.")
        return
    context.user_data.pop("awaiting_edit", None)
    context.user_data.pop("pending_signal_text", None)
    result = await _create_and_broadcast(update, context, raw_text)
    await update.message.reply_text(result)


async def _active_recipients(update: Update) -> List[str]:
    """Best-effort recipient list.

    The backend tracks registered testers by telegram id. In a private Telegram
    chat, that id is also the chat id, so the bot can broadcast trade cards to
    active testers without giving screenshot providers broad admin access.
    """
    recipients = {str(update.effective_chat.id)}
    data = await _backend_get(
        "/signals/recipients",
        headers=_signal_provider_headers(update.effective_user.id),
    )
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
