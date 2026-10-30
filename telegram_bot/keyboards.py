"""Inline keyboards and trade-card formatting for the Telegram bot."""
from __future__ import annotations

from typing import Any, Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def trade_card_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """YES/NO buttons. Callback data encodes the decision and signal id."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ YES: Place Demo Trade", callback_data=f"YES:{signal_id}"
                ),
                InlineKeyboardButton("❌ NO: Ignore", callback_data=f"NO:{signal_id}"),
            ]
        ]
    )


def extract_preview_keyboard(can_confirm: bool, preview_token: str) -> InlineKeyboardMarkup:
    """Bind actions to one preview; older Telegram messages cannot authorise another.

    The token is an opaque, per-preview hex identifier, not an authentication
    credential. Callback data stays below Telegram's 64-byte limit.
    """
    if len(preview_token) != 16 or any(ch not in "0123456789abcdef" for ch in preview_token):
        raise ValueError("Invalid preview identifier")
    rows = []
    if can_confirm:
        rows.append([
            InlineKeyboardButton("✅ Confirm & Send", callback_data=f"SIGOK:{preview_token}")
        ])
    rows.append(
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"SIGEDIT:{preview_token}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"SIGNO:{preview_token}"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def format_extraction_preview(data: Dict[str, Any]) -> str:
    """Human-readable preview of what was read from a screenshot."""
    valid = data.get("parser_status") == "VALID"
    lines = ["📷 Read from your screenshot:", ""]
    if data.get("extracted_text"):
        lines.append(f"“{data['extracted_text']}”")
        lines.append("")
    lines.append(f"Symbol: {data.get('symbol') or '—'}")
    lines.append(f"Direction: {data.get('direction') or '—'}")
    entry_type = data.get("entry_type") or "MARKET"
    entry = "Market" if entry_type == "MARKET" else _fmt(data.get("entry_price"))
    lines.append(f"Entry: {entry}")
    lines.append(f"SL: {_fmt(data.get('initial_stop_loss'))}")
    lines.append(f"TP1: {_fmt(data.get('tp1'))}")
    if data.get("tp2") is not None:
        lines.append(f"TP2: {_fmt(data.get('tp2'))}")
    if data.get("tp3") is not None:
        lines.append(f"TP3: {_fmt(data.get('tp3'))}")
    lines.append("")
    lines.append(f"Reader confidence: {data.get('confidence', 'LOW')} ({data.get('engine')})")
    if data.get("notes"):
        lines.append(f"Note: {data['notes']}")
    lines.append("")
    if valid:
        lines.append("✅ Passes safety checks. Confirm to send to testers, or Edit to fix.")
    else:
        lines.append(f"⚠️ Not valid yet: {data.get('parser_error')}")
        lines.append("Tap Edit to type the corrected signal, or Cancel.")
    return "\n".join(lines)


def _fmt(value) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else str(value)


def format_trade_card(signal: Dict[str, Any], expiry_minutes: int) -> str:
    """Build the human-readable trade card text from a parsed signal."""
    symbol = signal.get("symbol")
    direction = signal.get("direction")
    entry_type = signal.get("entry_type") or "MARKET"
    sl = signal.get("initial_stop_loss")
    tp1 = signal.get("tp1")
    tp2 = signal.get("tp2")
    tp3 = signal.get("tp3")

    lines = [
        "New Demo Signal",
        "",
        f"{symbol} {direction}",
        f"Entry: {'Market' if entry_type == 'MARKET' else _fmt(signal.get('entry_price'))}",
        f"Initial SL: {_fmt(sl)}",
        "",
    ]
    if tp1 is not None:
        lines.append(f"TP1: {_fmt(tp1)}")
        lines.append("Close TP1 child / move remaining SL to breakeven")
        lines.append("")
    if tp2 is not None:
        lines.append(f"TP2: {_fmt(tp2)}")
        lines.append("Close TP2 child / move remaining SL to TP1")
        lines.append("")
    if tp3 is not None:
        lines.append(f"TP3: {_fmt(tp3)}")
        lines.append("Close final child")
        lines.append("")

    lines.extend(
        [
            "Demo mode only.",
            "Split-ticket partial mode: ON",
            f"Expiry window: {expiry_minutes} minutes after signal creation",
            "",
            "Approve this demo trade?",
        ]
    )
    return "\n".join(lines)
