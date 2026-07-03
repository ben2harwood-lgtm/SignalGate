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
