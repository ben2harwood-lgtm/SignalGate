"""Fail closed on malformed numeric tokens rather than trusting valid prefixes.

All cases are pure-parser, broker-free evidence; no MT5 or pilot acceptance.
"""
from __future__ import annotations

import pytest

from app.parser import parse_signal


@pytest.mark.parametrize("signal", [
    "EURUSD BUY ENTRY 1.0850.2 SL 1.0800 TP1 1.0900",
    "EURUSD BUY ENTRY 1.0850abc SL 1.0800 TP1 1.0900",
    "EURUSD BUY ENTRY 1.0850% SL 1.0800 TP1 1.0900",
    "EURUSD BUY ENTRY later SL 1.0800 TP1 1.0900",
    "EURUSD BUY SL 1.0800.2 TP1 1.0900",
    "EURUSD BUY SL 1.0800abc TP1 1.0900",
    "EURUSD BUY SL 1.0800/1.0810 TP1 1.0900",
    "EURUSD BUY SL 1.0800_1 TP1 1.0900",
    "EURUSD BUY SL 1.0800 TP1 1.0900.1",
    "EURUSD BUY SL 1.0800 TP1 1.0900foo",
    "EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950%",
    "EURUSD BUY SL 1.0800 TP1 1.0900 TP2 1.0950 TP3 1.1000-1.2000",
])
def test_malformed_price_fields_never_produce_valid_trade(signal):
    result = parse_signal(signal)
    assert not result.is_valid
    assert "Malformed" in (result.parser_error or "")
    assert result.expires_at is None


@pytest.mark.parametrize("signal", [
    "EURUSD BUY ENTRY 1.0850 SL 1.0800 TP1 1.0900",
    "EURUSD BUY ENTRY MARKET SL 1.0800 TP1 1.0900",
    "EURUSD BUY SL: 1.0800, TP1: 1.0900; TP2: 1.0950",
    "XAUUSD BUY SL 2343 TP1 2353 TP2 2358",
])
def test_plain_decimal_and_market_formats_remain_valid(signal):
    assert parse_signal(signal).is_valid
