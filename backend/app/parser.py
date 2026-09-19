"""Deterministic, fail-closed signal parser.

Free-form provider text is untrusted input. The parser never guesses between
conflicting values: ambiguity, impossible prices, oversized payloads and
unsupported symbols are rejected before anything can become a trade command.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Optional

MAX_SIGNAL_TEXT_CHARS = 4000

SYMBOL_ALIASES = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "BTC": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "ETH": "ETHUSD",
    "ETHUSD": "ETHUSD",
}
BUY_WORDS = {"BUY", "LONG"}
SELL_WORDS = {"SELL", "SHORT"}

# Detect common FX pairs even when they are not supported instruments. Silently
# ignoring "EURUSD" beside "XAUUSD" would turn ambiguous provider text into a
# valid gold order, which violates the parser's fail-closed contract.
_CURRENCY_CODES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}


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
    parser_status: str = "REJECTED"
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


def _unique_match(pattern: str, text: str) -> tuple[Optional[str], bool]:
    """Return a value and whether conflicting repetitions were present."""
    values = re.findall(pattern, text, flags=re.IGNORECASE)
    if not values:
        return None, False
    normalised = {str(v).upper() for v in values}
    return str(values[0]), len(normalised) > 1


def _positive(value: Optional[float]) -> bool:
    return value is not None and value > 0


def parse_signal(
    raw_text: str,
    expiry_minutes: int = 5,
    now: Optional[dt.datetime] = None,
) -> ParseResult:
    now = now or dt.datetime.utcnow()
    result = ParseResult(raw_text=raw_text)

    if not raw_text or not raw_text.strip():
        return _reject(result, "Empty signal text")
    if len(raw_text) > MAX_SIGNAL_TEXT_CHARS:
        return _reject(result, "Signal text exceeds maximum length")

    upper = raw_text.strip().upper()
    upper = upper.replace("STOP LOSS", "SL").replace("STOPLOSS", "SL")
    upper = upper.replace("TAKE PROFIT", "TP").replace("TAKEPROFIT", "TP")

    symbol_tokens = re.findall(r"\b[A-Z]{3,6}\b", upper)
    canonical_symbols = {
        SYMBOL_ALIASES[token] for token in symbol_tokens if token in SYMBOL_ALIASES
    }
    unsupported_fx_pairs = {
        token
        for token in symbol_tokens
        if len(token) == 6
        and token not in SYMBOL_ALIASES
        and token[:3] in _CURRENCY_CODES
        and token[3:] in _CURRENCY_CODES
    }
    if unsupported_fx_pairs:
        if canonical_symbols:
            return _reject(
                result,
                "Multiple/unsupported instrument symbols present (ambiguous)",
            )
        return _reject(result, "Unsupported instrument symbol")
    if not canonical_symbols:
        return _reject(result, "No recognised symbol")
    if len(canonical_symbols) != 1:
        return _reject(result, "Multiple recognised symbols present (ambiguous)")
    result.symbol = next(iter(canonical_symbols))

    words = set(re.findall(r"[A-Z]+", upper))
    has_buy = bool(words & BUY_WORDS)
    has_sell = bool(words & SELL_WORDS)
    if has_buy and has_sell:
        return _reject(result, "Both BUY and SELL present (ambiguous)")
    if not has_buy and not has_sell:
        return _reject(result, "No direction found (expected BUY/SELL)")
    result.direction = "BUY" if has_buy else "SELL"

    entry_raw, ambiguous = _unique_match(
        r"\bENTRY\b\s*[:=]?\s*(MARKET|" + _NUM + r")", upper
    )
    if ambiguous:
        return _reject(result, "Conflicting ENTRY values present (ambiguous)")
    if entry_raw is None or entry_raw.upper() == "MARKET":
        result.entry_type = "MARKET"
    else:
        entry = _to_float(entry_raw)
        if not _positive(entry):
            return _reject(result, "Entry price must be positive")
        result.entry_type = "LIMIT"
        result.entry_price = entry

    sl_raw, ambiguous = _unique_match(
        r"\bSL\b\s*[:=]?\s*(" + _NUM + r")", upper
    )
    if ambiguous:
        return _reject(result, "Conflicting stop loss values present (ambiguous)")
    if sl_raw is None:
        return _reject(result, "No stop loss found")
    sl = _to_float(sl_raw)
    if not _positive(sl):
        return _reject(result, "Stop loss must be positive")
    result.initial_stop_loss = sl

    values = {}
    for level, pattern in (
        (1, r"\bTP1?\b\s*[:=]?\s*(" + _NUM + r")"),
        (2, r"\bTP2\b\s*[:=]?\s*(" + _NUM + r")"),
        (3, r"\bTP3\b\s*[:=]?\s*(" + _NUM + r")"),
    ):
        raw, ambiguous = _unique_match(pattern, upper)
        if ambiguous:
            return _reject(result, f"Conflicting TP{level} values present (ambiguous)")
        if raw is not None:
            value = _to_float(raw)
            if not _positive(value):
                return _reject(result, f"TP{level} must be positive")
            values[level] = value

    if 1 not in values:
        return _reject(result, "No TP1 found")
    result.tp1 = values.get(1)
    result.tp2 = values.get(2)
    result.tp3 = values.get(3)

    tps = [t for t in (result.tp1, result.tp2, result.tp3) if t is not None]
    if result.direction == "BUY":
        if any(sl >= t for t in tps):
            return _reject(result, "BUY stop loss must be below take profits")
        if not _strictly_increasing(tps):
            return _reject(result, "BUY take profits must increase: TP1<TP2<TP3")
        if result.entry_price is not None:
            if sl >= result.entry_price:
                return _reject(result, "BUY stop loss must be below entry price")
            if result.entry_price >= result.tp1:
                return _reject(result, "BUY entry must be below TP1")
    else:
        if any(sl <= t for t in tps):
            return _reject(result, "SELL stop loss must be above take profits")
        if not _strictly_decreasing(tps):
            return _reject(result, "SELL take profits must decrease: TP1>TP2>TP3")
        if result.entry_price is not None:
            if sl <= result.entry_price:
                return _reject(result, "SELL stop loss must be above entry price")
            if result.entry_price <= result.tp1:
                return _reject(result, "SELL entry must be above TP1")

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
