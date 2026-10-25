"""Source-only guard for the external acceptance handoff's failed frozen-RC2 gate.

These assertions do not compile MQL5, connect to a broker, or close external
acceptance. They prevent a historically failed EA being presented as ready.
"""
from pathlib import Path

HANDOFF = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "EXTERNAL_ACCEPTANCE_HANDOFF.md"
)


def test_handoff_names_failed_frozen_compiler_and_preserves_ci_distinction() -> None:
    doc = HANDOFF.read_text(encoding="utf-8")
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in doc
    assert "35464044898" in doc
    assert "18 errors, 4 warnings" in doc
    assert "35459129106" in doc
    assert "not a MetaEditor pass" in doc


def test_handoff_withholds_frozen_rc2_broker_demo_and_requires_successor() -> None:
    doc = HANDOFF.read_text(encoding="utf-8")
    assert "Do not use" in doc and "frozen RC2 EA for broker-demo acceptance" in doc
    assert "independently reviewed" in doc
    assert "successor candidate" in doc
    assert "0 errors / 0 warnings" in doc
    assert "newly generated EX5" in doc
    assert "PR #60" in doc
    assert "NOT_RUN" in doc
    assert "ON HOLD" in doc


def test_handoff_does_not_promote_machine_or_synthetic_evidence() -> None:
    doc = HANDOFF.read_text(encoding="utf-8")
    assert "source-level test" in doc
    assert "actual MT5 terminal/broker result" in doc
    assert "No real-money or" in doc
    assert "automatic-copy operation is authorised" in doc
    assert "Do not use real-money accounts." in doc
