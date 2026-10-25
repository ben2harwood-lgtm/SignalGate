"""Static release-gate contract: offline tests, not MT5 acceptance evidence."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _g3_section() -> str:
    text = (REPO_ROOT / "docs" / "RELEASE_GATES.md").read_text(encoding="utf-8")
    start = "## G3 — Execution safety"
    end = "## G4 — Adversarial ingestion"
    assert text.count(start) == 1
    assert text.count(end) == 1
    return text.split(start, 1)[1].split(end, 1)[0]


def test_g3_requires_exact_candidate_official_compile_and_ex5():
    gate = _g3_section()
    for requirement in (
        "official MetaEditor receipt",
        "candidate SHA",
        "EA-source hash",
        "0 errors / 0 warnings",
        "nonempty EX5",
        "failed frozen candidate",
    ):
        assert requirement in gate


def test_g3_requires_real_demo_broker_evidence_not_synthetic_substitution():
    gate = _g3_section()
    for requirement in (
        "Actual MT5 demo-broker proof",
        "docs/MT5_ACCEPTANCE.md",
        "deal/order/position identities",
        "multi-fill",
        "weighted execution price",
        "partial/manual/TP exits",
        "NOT_RUN",
    ):
        assert requirement in gate


def test_g3_stays_on_hold_without_review_and_broker_reconciliation():
    gate = _g3_section()
    for requirement in (
        "independently review",
        "ambiguous sends",
        "restart recovery",
        "conflicting broker evidence",
        "OPEN/HOLD",
        "automated CI alone cannot pass",
    ):
        assert requirement in gate
