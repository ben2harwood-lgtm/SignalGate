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

# --- Symbol recognition ---------------------------------------------------
#
# A trading symbol is a pair of two "legs" (base + quote), e.g. EURUSD, GBPJPY,
# XAUUSD (gold), BTCUSD. We recognise any pair built from the known legs below,
# so forex majors/minors/crosses are all supported (not just gold). This stays
# deterministic and bounded: a leg must be a currency/metal/crypto code we know,
# so random 6-letter words are still rejected.

FIAT_CODES = {
    "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF",
    "SEK", "NOK", "DKK", "SGD", "HKD", "MXN", "ZAR", "TRY",
    "PLN", "CZK", "HUF", "CNH",
}
METAL_CODES = {"XAU", "XAG", "XPT", "XPD"}       # gold, silver, platinum, palladium
CRYPTO_CODES = {"BTC", "ETH", "LTC", "XRP", "BCH", "SOL", "ADA", "DOT", "BNB"}
PAIR_CODES = FIAT_CODES | METAL_CODES | CRYPTO_CODES

# Whole-word convenience aliases -> canonical pair (how people often write them).
SYMBOL_WORD_ALIASES = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
}

BUY_WORDS = {"BUY", "LONG"}
SELL_WORDS = {"SELL", "SHORT"}


def _detect_symbol(upper: str) -> Optional[str]:
    """Find the first recognised trading symbol in the (upper-cased) text.

    Accepts concatenated pairs (EURUSD, GBPJPY, XAUUSD), separator forms
    (EUR/USD, GBP-JPY), and the whole-word aliases (GOLD, SILVER, BTC, ETH).
    Returns the canonical 6-letter symbol, or None if nothing recognised.
    """
    # Join separator forms so "EUR/USD" / "GBP-JPY" become one token. Only
    # slash/dash between two 3-letter codes are joined (spaces are NOT, so
    # "BUY EUR/USD" is not mangled into "BUYEUR").
    joined = re.sub(r"\b([A-Z]{3})[/\-]([A-Z]{3})\b", r"\1\2", upper)
    for token in re.findall(r"[A-Z]{3,6}", joined):
        if len(token) == 6:
            base, quote = token[:3], token[3:]
            if base in PAIR_CODES and quote in PAIR_CODES:
                return base + quote
        if token in SYMBOL_WORD_ALIASES:
            return SYMBOL_WORD_ALIASES[token]
    return None


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
    allowed_symbols: Optional[set] = None,
) -> ParseResult:
    """Parse raw signal text into structured fields, validating safety rules.

    Supports both multi-line ("SL: 2343") and single-line
    ("... SL 2343 TP1 2353 ...") layouts.

    allowed_symbols: optional set of canonical symbols the operator has enabled
    (e.g. {"EURUSD","GBPJPY"}). When provided, a recognised-but-not-enabled
    symbol is rejected. When None (default) every recognised pair is allowed.
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

    # --- Malformed-number guard ------------------------------------------
    # SAFETY: the number extractor (_NUM) stops at the first non-numeric
    # character, so "2,343" would silently become 2.0 and "2e3" would become
    # 2.0 — a catastrophic (or zero) stop loss that still passes every
    # directional check downstream. Refuse these formats outright rather than
    # guess a price. A comma directly between digits (thousands separator or
    # euro decimal) and scientific notation are both rejected.
    if re.search(r"\d,\d", upper):
        return _reject(
            result,
            "Numbers must not contain commas — write 2343 or 2343.50, not 2,343",
        )
    if re.search(r"\d[eE][-+]?\d", upper):
        return _reject(result, "Scientific notation is not allowed in prices")

    # --- Symbol -----------------------------------------------------------
    symbol = _detect_symbol(upper)
    if symbol is None:
        return _reject(
            result,
            "No recognised symbol. Use a forex pair (e.g. EURUSD, GBPJPY), a "
            "metal (XAUUSD/GOLD), or crypto (BTCUSD). Indices/CFDs are not "
            "supported in v1.",
        )
    if allowed_symbols is not None and symbol not in allowed_symbols:
        return _reject(
            result,
            f"Symbol {symbol} is not enabled for trading on this desk.",
        )
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

    # SAFETY: every price must be a positive, finite number. A zero or
    # negative stop/target is never a real level and would produce a nonsense
    # trade if it reached MetaTrader.
    all_prices = [p for p in (result.entry_price, sl, *tps) if p is not None]
    if any(p <= 0 for p in all_prices):
        return _reject(result, "Prices must be positive numbers")

    # SAFETY: plausibility backstop. A mis-parse (e.g. a truncated stop of 2.0
    # for gold at 2350) leaves the stop loss sitting more than half the price
    # away from TP1. No real signal has a stop that far from its first target,
    # so treat it as a mis-read level and reject rather than trade it.
    if abs(sl - result.tp1) > 0.5 * result.tp1:
        return _reject(
            result,
            "Stop loss is implausibly far from TP1 (possible mis-read number)",
        )

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
