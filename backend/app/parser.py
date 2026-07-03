"""Deterministic signal parser.

SAFETY: This is the ONLY thing that turns free Telegram text into structured
trade data. There is deliberately no AI / fuzzy parsing here. If anything is
ambiguous or unsafe, we REJECT rather than guess. Raw text never flows past
this boundary to MetaTrader.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Optional

# --- Alias maps -----------------------------------------------------------

SYMBOL_ALIASES = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAUUSD": "XAUUSD",
    # Crypto (trades 24/7, incl. weekends). Map to broker symbol names.
    "BTC": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "ETH": "ETHUSD",
    "ETHUSD": "ETHUSD",
}

BUY_WORDS = {"BUY", "LONG"}
SELL_WORDS = {"SELL", "SHORT"}


@dataclass
class ParseResult:
    raw_text: str
    symbol: Optional[str] = None
    direction: Optional[str] = None
    entry_type: Optional[str] = None
    entry_price: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    parser_status: str = "REJECTED"  # VALID / REJECTED
    parser_error: Optional[str] = None
    expires_at: Optional[dt.datetime] = None
    errors: list = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.parser_status == "VALID"


_NUM = r"[-+]?\d+(?:\.\d+)?"


def _to_float(token: str) -> Optional[float]:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def _find_first(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def parse_signal(
    raw_text: str,
    expiry_minutes: int = 5,
    now: Optional[dt.datetime] = None,
) -> ParseResult:
    """Parse raw signal text into structured fields, validating safety rules.

    Supports both multi-line ("SL: 2343") and single-line
    ("... SL 2343 TP1 2353 ...") layouts.
    """
    now = now or dt.datetime.utcnow()
    result = ParseResult(raw_text=raw_text)

    if not raw_text or not raw_text.strip():
        return _reject(result, "Empty signal text")

    text = raw_text.strip()
    upper = text.upper()
    # Normalise so "STOP LOSS" / "TAKE PROFIT" become single tokens.
    upper = upper.replace("STOP LOSS", "SL").replace("STOPLOSS", "SL")
    upper = upper.replace("STOP", "SL")
    upper = upper.replace("TAKE PROFIT", "TP").replace("TAKEPROFIT", "TP")

    # --- Symbol -----------------------------------------------------------
    symbol = None
    for token in re.findall(r"[A-Z]{3,6}", upper):
        if token in SYMBOL_ALIASES:
            symbol = SYMBOL_ALIASES[token]
            break
    if symbol is None:
        return _reject(result, "No recognised symbol (expected GOLD/XAU/XAUUSD)")
    result.symbol = symbol

    # --- Direction --------------------------------------------------------
    words = set(re.findall(r"[A-Z]+", upper))
    has_buy = bool(words & BUY_WORDS)
    has_sell = bool(words & SELL_WORDS)
    if has_buy and has_sell:
        return _reject(result, "Both BUY and SELL present (ambiguous)")
    if not has_buy and not has_sell:
        return _reject(result, "No direction found (expected BUY/SELL)")
    result.direction = "BUY" if has_buy else "SELL"

    # --- Entry ------------------------------------------------------------
    # Entry is optional. If "Entry: Market" -> MARKET. If a price is given,
    # treat as LIMIT. Default to MARKET when absent.
    entry_raw = _find_first(r"ENTRY\s*[:=]?\s*(MARKET|" + _NUM + r")", upper)
    if entry_raw is None:
        result.entry_type = "MARKET"
        result.entry_price = None
    elif entry_raw.upper() == "MARKET":
        result.entry_type = "MARKET"
        result.entry_price = None
    else:
        price = _to_float(entry_raw)
        if price is None:
            return _reject(result, "Invalid entry price")
        result.entry_type = "LIMIT"
        result.entry_price = price

    # --- Stop loss --------------------------------------------------------
    # Match SL but NOT a TP token. Use word boundary; SL followed by optional
    # ':' or '=' then number.
    sl_raw = _find_first(r"\bSL\b\s*[:=]?\s*(" + _NUM + r")", upper)
    if sl_raw is None:
        return _reject(result, "No stop loss found")
    sl = _to_float(sl_raw)
    if sl is None:
        return _reject(result, "Invalid stop loss value")
    result.initial_stop_loss = sl

    # --- Take profits -----------------------------------------------------
    tp1_raw = _find_first(r"\bTP1?\b\s*[:=]?\s*(" + _NUM + r")", upper)
    tp2_raw = _find_first(r"\bTP2\b\s*[:=]?\s*(" + _NUM + r")", upper)
    tp3_raw = _find_first(r"\bTP3\b\s*[:=]?\s*(" + _NUM + r")", upper)

    if tp1_raw is None:
        return _reject(result, "No TP1 found")
    tp1 = _to_float(tp1_raw)
    if tp1 is None:
        return _reject(result, "Invalid TP1 value")
    result.tp1 = tp1

    if tp2_raw is not None:
        tp2 = _to_float(tp2_raw)
        if tp2 is None:
            return _reject(result, "Invalid TP2 value")
        result.tp2 = tp2
    if tp3_raw is not None:
        tp3 = _to_float(tp3_raw)
        if tp3 is None:
            return _reject(result, "Invalid TP3 value")
        result.tp3 = tp3

    # --- Directional sanity checks ---------------------------------------
    # Reference price for SL validity: entry price if given, else TP1 side.
    tps = [t for t in (result.tp1, result.tp2, result.tp3) if t is not None]

    if result.direction == "BUY":
        # SL must be below all TP levels.
        if any(sl >= t for t in tps):
            return _reject(result, "BUY stop loss must be below take profits")
        # TP ordering ascending.
        if not _strictly_increasing(tps):
            return _reject(result, "BUY take profits must increase: TP1<TP2<TP3")
        if result.entry_price is not None and sl >= result.entry_price:
            return _reject(result, "BUY stop loss must be below entry price")
    else:  # SELL
        if any(sl <= t for t in tps):
            return _reject(result, "SELL stop loss must be above take profits")
        if not _strictly_decreasing(tps):
            return _reject(result, "SELL take profits must decrease: TP1>TP2>TP3")
        if result.entry_price is not None and sl <= result.entry_price:
            return _reject(result, "SELL stop loss must be above entry price")

    # --- Success ----------------------------------------------------------
    result.parser_status = "VALID"
    result.parser_error = None
    result.expires_at = now + dt.timedelta(minutes=expiry_minutes)
    return result


def _strictly_increasing(values: list) -> bool:
    return all(a < b for a, b in zip(values, values[1:]))


def _strictly_decreasing(values: list) -> bool:
    return all(a > b for a, b in zip(values, values[1:]))


def _reject(result: ParseResult, message: str) -> ParseResult:
    result.parser_status = "REJECTED"
    result.parser_error = message
    result.errors.append(message)
    return result
