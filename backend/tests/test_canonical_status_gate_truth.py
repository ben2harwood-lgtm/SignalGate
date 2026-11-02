"""Guard the canonical SignalGate status against retroactive RC2 acceptance claims.

Source facts: failed official MetaEditor workflow 35464044898 and repaired
PR #55 workflow 35464509608. No broker/demo assertions are made here.
"""
from pathlib import Path

STATUS = Path(__file__).resolve().parents[2] / "SIGNALGATE-STATUS.md"


def _status() -> str:
    return STATUS.read_text(encoding="utf-8")


def test_exact_frozen_rc2_compile_failure_is_explicit() -> None:
    data = _status()
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in data
    assert "35464044898" in data
    assert "18 errors / 4 warnings" in data
    assert "FAILED" in data


def test_repaired_compiler_receipt_cannot_clear_frozen_rc2() -> None:
    data = _status()
    assert "d2dc404c94db02bd2d21cfa5a37674bfd748dea4" in data
    assert "35464509608" in data
    assert "cannot retroactively clear" in data
    assert "Use RC2 for all new external/manual acceptance work" not in data


def test_mt5_broker_demo_and_real_money_remain_blocked() -> None:
    data = _status()
    section = data.split("## Frozen RC2 compiler exception — verified 23 October 2026", 1)[1]
    section = section.split("\n## RC2 improvements over RC1", 1)[0]
    assert "Gate remains OPEN" in section
    assert "PR #60" in section
    assert "Real-money and automatic copying remain blocked" in section


ROOT = Path(__file__).resolve().parents[2]
ROOT_GUIDES = (ROOT / "READ ME FIRST.txt", ROOT / "INSTALL_AND_USER_GUIDE.md")


def test_root_guides_disclose_failed_frozen_rc2_compiler() -> None:
    for path in ROOT_GUIDES:
        content = path.read_text(encoding="utf-8")
        assert "release/signalgate-demo-rc2-2026-09-19" in content
        assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in content
        assert "35464044898" in content
        assert "18 errors / 4 warnings" in content
        assert "FAILED" in content


def test_root_guides_cannot_direct_frozen_rc2_into_broker_acceptance() -> None:
    for path in ROOT_GUIDES:
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        assert ("do not use the frozen rc2 ea" in lowered
                or "do **not** use frozen rc2" in lowered)
        assert "PR #60" in content
        assert "independently reviewed" in content
        assert "0-error / 0-warning" in content
        assert "EX5" in content
        assert "DEMO broker" in content


def test_root_guides_keep_ci_separate_from_broker_acceptance() -> None:
    for path in ROOT_GUIDES:
        content = path.read_text(encoding="utf-8").lower()
        assert "green backend ci" in content
        assert "cannot clear" in content
        assert "real-money" in content
