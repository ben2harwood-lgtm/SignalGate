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


def extract_preview_keyboard(can_confirm: bool = True) -> InlineKeyboardMarkup:
    """Confirm / Edit / Cancel buttons for a signal extracted from a screenshot.

    No id is encoded: the candidate text is held in the bot's per-user state
    until the provider confirms, edits, or cancels.
    """
    rows = []
    if can_confirm:
        rows.append([InlineKeyboardButton("✅ Confirm & Send", callback_data="SIGOK")])
    rows.append(
        [
            InlineKeyboardButton("✏️ Edit", callback_data="SIGEDIT"),
            InlineKeyboardButton("❌ Cancel", callback_data="SIGNO"),
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
            f"Expires in: {expiry_minutes} minutes",
            "",
            "Approve this demo trade?",
        ]
    )
    return "\n".join(lines)
