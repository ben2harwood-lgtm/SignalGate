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


def test_multiple_recognised_symbols_rejected():
    r = parse_signal("XAUUSD BTCUSD BUY SL 2343 TP1 2353")
    assert not r.is_valid
    assert "symbols" in (r.parser_error or "").lower()


def test_conflicting_stop_losses_rejected():
    r = parse_signal("XAUUSD BUY SL 2343 SL 2000 TP1 2353")
    assert not r.is_valid
    assert "conflicting stop" in (r.parser_error or "").lower()


def test_conflicting_tp1_values_rejected():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353 TP1 2400")
    assert not r.is_valid
    assert "conflicting tp1" in (r.parser_error or "").lower()


def test_repeated_identical_value_is_tolerated():
    r = parse_signal("XAUUSD BUY SL 2343 SL 2343 TP1 2353 TP1 2353")
    assert r.is_valid


def test_non_positive_prices_rejected():
    assert not parse_signal("XAUUSD BUY SL -1 TP1 2353").is_valid
    assert not parse_signal("XAUUSD SELL SL 2355 TP1 0").is_valid


def test_limit_entry_must_be_between_sl_and_tp1():
    assert not parse_signal("XAUUSD BUY ENTRY 2400 SL 2343 TP1 2353").is_valid
    assert not parse_signal("XAUUSD SELL ENTRY 2300 SL 2355 TP1 2345").is_valid


def test_oversized_signal_text_rejected():
    r = parse_signal("XAUUSD BUY SL 2343 TP1 2353 " + ("X" * 5000))
    assert not r.is_valid
    assert "maximum length" in (r.parser_error or "").lower()


def test_forex_major_pairs_and_crosses_valid():
    eur = parse_signal("EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950")
    gbpjpy = parse_signal("GBPJPY SELL SL 191.00 TP1 189.00 TP2 188.00")
    assert eur.is_valid and eur.symbol == "EURUSD"
    assert gbpjpy.is_valid and gbpjpy.symbol == "GBPJPY"


def test_forex_separator_forms_are_canonicalised():
    assert parse_signal("EUR/USD BUY SL 1.08 TP1 1.09").symbol == "EURUSD"
    assert parse_signal("GBP-JPY SELL SL 191 TP1 189").symbol == "GBPJPY"


def test_index_like_symbol_stays_rejected():
    r = parse_signal("US30 BUY SL 38000 TP1 39000")
    assert not r.is_valid


def test_allowed_symbols_restricts_deployment():
    allowed = {"EURUSD", "GBPUSD"}
    assert parse_signal(
        "EURUSD BUY SL 1.08 TP1 1.09",
        allowed_symbols=allowed,
    ).is_valid
    blocked = parse_signal(
        "GBPJPY SELL SL 191 TP1 189",
        allowed_symbols=allowed,
    )
    assert not blocked.is_valid
    assert "not enabled" in (blocked.parser_error or "").lower()


def test_comma_and_scientific_prices_fail_closed():
    comma = parse_signal("XAUUSD BUY SL 2,343 TP1 2353")
    sci = parse_signal("XAUUSD BUY SL 2e3 TP1 2353")
    assert not comma.is_valid
    assert "comma" in (comma.parser_error or "").lower()
    assert not sci.is_valid
    assert "scientific" in (sci.parser_error or "").lower()


def test_multiple_forex_symbols_are_ambiguous():
    r = parse_signal("EURUSD GBPUSD BUY SL 1.08 TP1 1.09")
    assert not r.is_valid
    assert "multiple" in (r.parser_error or "").lower()
