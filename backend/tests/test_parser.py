"""Deterministic parser tests (the 10 required cases plus formats)."""
from __future__ import annotations

from app.parser import parse_signal


def test_1_valid_full_buy():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363")
    assert r.is_valid
    assert r.symbol == "XAUUSD"
    assert r.direction == "BUY"
    assert r.initial_stop_loss == 2343
    assert r.tp1 == 2353 and r.tp2 == 2358 and r.tp3 == 2363


def test_2_valid_gold_two_tps():
    r = parse_signal("GOLD BUY SL 2343 TP1 2353 TP2 2358")
    assert r.is_valid
    assert r.symbol == "XAUUSD"
    assert r.tp3 is None


def test_3_valid_xau_sell():
    r = parse_signal("XAU SELL SL 2355 TP1 2345 TP2 2340")
    assert r.is_valid
    assert r.direction == "SELL"
    assert r.symbol == "XAUUSD"


def test_4_rejected_missing_sl():
    r = parse_signal("BUY XAUUSD TP1 2353")
    assert not r.is_valid
    assert "stop loss" in (r.parser_error or "").lower()


def test_5_random_text_rejected():
    r = parse_signal("hello world how are you today")
    assert not r.is_valid


def test_6_both_buy_and_sell_rejected():
    r = parse_signal("XAUUSD BUY SELL SL 2343 TP1 2353")
    assert not r.is_valid
    assert "both" in (r.parser_error or "").lower()


def test_7_buy_sl_above_tp_rejected():
    r = parse_signal("XAUUSD BUY SL 2360 TP1 2353 TP2 2358")
    assert not r.is_valid
    assert "below" in (r.parser_error or "").lower()


def test_8_sell_sl_below_tp_rejected():
    r = parse_signal("XAU SELL SL 2340 TP1 2345 TP2 2350")
    assert not r.is_valid
    assert "above" in (r.parser_error or "").lower()


def test_9_buy_tp2_lower_than_tp1_rejected():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353 TP2 2350")
    assert not r.is_valid


def test_10_sell_tp2_higher_than_tp1_rejected():
    r = parse_signal("XAU SELL SL 2360 TP1 2350 TP2 2355")
    assert not r.is_valid


def test_multiline_format_valid():
    text = (
        "XAUUSD BUY\n"
        "Entry: Market\n"
        "SL: 2343\n"
        "TP1: 2353\n"
        "TP2: 2358\n"
        "TP3: 2363\n"
    )
    r = parse_signal(text)
    assert r.is_valid
    assert r.entry_type == "MARKET"
    assert r.tp3 == 2363


def test_expiry_is_set_for_valid():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353", expiry_minutes=5)
    assert r.is_valid
    assert r.expires_at is not None


# --- Malformed / unsafe number handling (P0-1 / P1-4) --------------------

def test_crypto_symbols_valid():
    assert parse_signal("BTCUSD BUY SL 60000 TP1 62000 TP2 64000").is_valid
    assert parse_signal("ETH SELL SL 3600 TP1 3500").is_valid


# --- Forex pair support (multi-symbol, not gold-only) --------------------

def test_forex_major_pairs_valid():
    r = parse_signal("EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950 TP3 1.1000")
    assert r.is_valid and r.symbol == "EURUSD" and r.direction == "BUY"
    r2 = parse_signal("USDJPY BUY SL 147.50 TP1 148.50 TP2 149.00")
    assert r2.is_valid and r2.symbol == "USDJPY"


def test_forex_cross_pair_sell_valid():
    r = parse_signal("GBPJPY SELL SL 191.00 TP1 189.00 TP2 188.00")
    assert r.is_valid and r.symbol == "GBPJPY" and r.direction == "SELL"


def test_forex_separator_forms_valid():
    assert parse_signal("EUR/USD BUY SL 1.08 TP1 1.09 TP2 1.10").symbol == "EURUSD"
    assert parse_signal("GBP-JPY SELL SL 191 TP1 189 TP2 187").symbol == "GBPJPY"


def test_index_symbol_rejected():
    # Indices / CFDs are out of scope in v1 and must reject cleanly.
    r = parse_signal("US30 BUY SL 38000 TP1 39000")
    assert not r.is_valid
    assert "symbol" in (r.parser_error or "").lower()


def test_allowed_symbols_restricts_desk():
    # With an operator allowlist, a recognised-but-not-enabled pair is rejected.
    allowed = {"EURUSD", "GBPUSD"}
    assert parse_signal("EURUSD BUY SL 1.08 TP1 1.09", allowed_symbols=allowed).is_valid
    blocked = parse_signal("GBPJPY SELL SL 191 TP1 189", allowed_symbols=allowed)
    assert not blocked.is_valid
    assert "not enabled" in (blocked.parser_error or "").lower()


def test_comma_grouped_number_rejected():
    # "2,343" must NOT be silently truncated to 2.0 and marked VALID.
    r = parse_signal("XAUUSD BUY SL 2,343 TP1 2353 TP2 2358 TP3 2363")
    assert not r.is_valid
    assert "comma" in (r.parser_error or "").lower()


def test_euro_decimal_comma_rejected():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353,50")
    assert not r.is_valid
    assert "comma" in (r.parser_error or "").lower()


def test_scientific_notation_rejected():
    r = parse_signal("XAUUSD BUY SL 2e3 TP1 2353")
    assert not r.is_valid
    assert "scientific" in (r.parser_error or "").lower()


def test_negative_price_rejected():
    r = parse_signal("XAUUSD BUY SL -2343 TP1 2353")
    assert not r.is_valid
    assert "positive" in (r.parser_error or "").lower()


def test_zero_price_rejected():
    r = parse_signal("XAUUSD BUY SL 0 TP1 2353")
    assert not r.is_valid
    assert "positive" in (r.parser_error or "").lower()


def test_implausible_stop_distance_rejected():
    # A truncated/mis-read stop (2 for gold at ~2353) sits > 50% from TP1.
    r = parse_signal("XAUUSD BUY SL 2 TP1 2353")
    assert not r.is_valid
    assert "implausibl" in (r.parser_error or "").lower()
