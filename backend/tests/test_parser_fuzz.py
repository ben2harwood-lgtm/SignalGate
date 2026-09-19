"""Deterministic fuzz/property tests for the fail-closed signal parser."""
from __future__ import annotations

import random
import string

from app.parser import parse_signal


def test_parser_does_not_crash_on_2000_deterministic_hostile_inputs():
    rng = random.Random(0x51A1A7E)
    alphabet = (
        string.ascii_letters
        + string.digits
        + string.punctuation
        + " \t\n\r"
        + "£€¥→←±×÷🚨📈📉"
    )
    for _ in range(2000):
        length = rng.randint(0, 700)
        raw = "".join(rng.choice(alphabet) for _ in range(length))
        parsed = parse_signal(raw)
        assert parsed.parser_status in {"VALID", "REJECTED"}
        if parsed.parser_status == "VALID":
            # Even a random string that happens to contain a syntactically valid
            # signal must emerge with the safety-critical fields populated.
            assert parsed.symbol
            assert parsed.direction in {"BUY", "SELL"}
            assert parsed.initial_stop_loss is not None
            assert parsed.tp1 is not None


def test_conflicting_repeated_core_fields_fail_closed():
    corpus = [
        "XAUUSD EURUSD BUY SL 2300 TP1 2400",
        "XAUUSD BUY SELL SL 2300 TP1 2400",
        "XAUUSD BUY SL 2300 SL 2310 TP1 2400",
        "XAUUSD BUY SL 2300 TP1 2400 TP1 2410",
        "XAUUSD BUY ENTRY 2350 ENTRY 2360 SL 2300 TP1 2400",
    ]
    for raw in corpus:
        parsed = parse_signal(raw)
        assert parsed.parser_status == "REJECTED", raw


def test_non_finite_or_non_positive_trade_levels_fail_closed():
    corpus = [
        "XAUUSD BUY SL 0 TP1 2400",
        "XAUUSD BUY SL -1 TP1 2400",
        "XAUUSD BUY SL 2300 TP1 0",
        "XAUUSD BUY SL 2300 TP1 -5",
        "XAUUSD BUY ENTRY 0 SL 2300 TP1 2400",
    ]
    for raw in corpus:
        parsed = parse_signal(raw)
        assert parsed.parser_status == "REJECTED", raw
