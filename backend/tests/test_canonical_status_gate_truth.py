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


ACCEPTANCE_INDEX = ROOT / "docs" / "ACCEPTANCE_EVIDENCE_INDEX.md"
RELEASE_RECEIPT = ROOT / "docs" / "RELEASE_CANDIDATE_2026-09-19.md"


def test_acceptance_index_records_failed_frozen_rc2_compiler_gate() -> None:
    """A green historical CI run cannot leave the compiler row as merely Open."""
    data = ACCEPTANCE_INDEX.read_text(encoding="utf-8")
    row = next(
        line for line in data.splitlines()
        if line.startswith("| MetaEditor compile |")
    )
    assert "**HOLD — frozen RC2 failed**" in row
    assert "35464044898" in row
    assert "18 errors / 4 warnings" in row
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in data
    assert "35462909294" in data
    assert "Do **not** use frozen RC2's EA" in data
    assert "RC2 must not be used for external acceptance until" not in data


def test_release_receipt_refuses_failed_rc2_mt5_acceptance() -> None:
    """Retrospective ledger remains separate from successor and real broker proof."""
    data = RELEASE_RECEIPT.read_text(encoding="utf-8")
    assert "RETROSPECTIVE MT5 COMPILER HOLD" in data
    assert "3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2" in data
    assert "35464044898" in data
    assert "18 errors / 4 warnings" in data
    assert "independently reviewed successor" in data
    assert "0-error / 0-warning" in data
    assert "matching EX5" in data
    assert "genuine controlled" in data and "DEMO" in data
    assert "Still required against RC2:" not in data
    assert "RC2 supersedes RC1 for new acceptance work" not in data

def test_new_acceptance_receipt_identifiers_do_not_impersonate_frozen_rc2() -> None:
    """New demo receipts must be bound to their own candidate, not failed RC2."""
    data = ACCEPTANCE_INDEX.read_text(encoding="utf-8")
    naming = data.split("## Controlled data-room naming", 1)[1]
    assert "SG-<FULL-40-CHAR-CANDIDATE-SHA>/" in naming
    assert "There is **no accepted successor candidate yet**" in naming
    assert "SG-RC2-2026-09-19/mt5/" not in naming
    assert "must never" in naming
    assert "FAILED/HOLD" in naming
    assert "A naming convention supplies no such proof" in naming

def test_pending_telegram_epoch_revision_is_distinct_from_main_and_rc2() -> None:
    """Proposed schema changes must not masquerade as merged RC2/main facts."""
    data = _status()
    heading = "### Draft migration `20261101_0011` is not the RC2/main schema"
    assert data.count(heading) == 1
    draft = data.split(heading, 1)[1].split("\n## ", 1)[0]
    assert "20260919_0010" in draft
    assert "20261101_0011_source_authorization_epoch.py" in draft
    assert "Unmerged draft PRs #168/#172" in draft
    assert "NOT ON MAIN" in draft
    assert "not an approved deployment" in draft
    assert "populated-database" in draft
    assert "isolated restore" in draft
    assert "do not" in draft.lower()
    assert "do not** clear G3/G8/G9" in draft
