"""Receipt tooling must not award a PASS for absent/skipped/dirty-candidate tests."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/run_broker_free_rehearsal.py"
spec = importlib.util.spec_from_file_location("broker_free_rehearsal", SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@pytest.mark.parametrize("body", [
    '<testsuite/>',
    '<testsuite><testcase name="test_expected"><skipped/></testcase></testsuite>',
    '<testsuite><testcase name="test_expected"><failure/></testcase></testsuite>',
    '<testsuite><testcase name="test_expected"><error/></testcase></testsuite>',
    '<testsuite><testcase name="test_different"/></testsuite>',
    '<testsuite><testcase name="test_expected"/><testcase name="test_expected"/></testsuite>',
    'malformed',
])
def test_junit_cannot_hide_absent_skipped_or_failed_scenarios(tmp_path, body):
    report = tmp_path / "report.xml"
    report.write_text(body)
    assert harness.junit_result(report, ["tests/a.py::test_expected"])["passed"] is False


def test_invalid_candidate_does_not_create_output(tmp_path):
    output = tmp_path / "evidence"
    with pytest.raises(ValueError):
        harness.run(tmp_path, "main", output)
    assert not output.exists()


@pytest.mark.parametrize("mutate_archive", [False, True])
def test_rehearsal_uses_committed_archive_not_dirty_working_copy(tmp_path, monkeypatch, mutate_archive):
    repo = tmp_path / "repo"
    (repo / "backend/tests").mkdir(parents=True)
    (repo / "mt5_ea").mkdir()
    source = repo / "mt5_ea/SignalGateEA.mq5"
    source.write_text("committed source\n")
    test = repo / "backend/tests/test_snapshot.py"
    test.write_text("from pathlib import Path\ndef test_committed():\n    assert True\n" + ("    Path('../mt5_ea/SignalGateEA.mq5').write_text('tampered archive')\n" if mutate_archive else ""))
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init")
    git("add", ".")
    git("-c", "user.name=Rehearsal Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    candidate = git("rev-parse", "HEAD")
    committed_hash = harness.sha256(source)
    source.write_text("dirty source\n")
    test.write_text("def test_committed():\n    assert False\n")
    monkeypatch.setattr(harness, "SCENARIOS", (("fixture", "synthetic_api", "tests/test_snapshot.py::test_committed"),))
    monkeypatch.setattr(harness, "EXTRA_TESTS", ())
    output = tmp_path / "receipt"
    receipt = harness.run(repo, candidate, output)
    assert receipt["result"] == ("REHEARSAL_FAIL" if mutate_archive else "REHEARSAL_PASS")
    assert receipt["source_stable"] is not mutate_archive
    assert receipt["candidate_sha"] == candidate
    assert receipt["candidate_ea_source_sha256"] == committed_hash
    assert receipt["actual_mt5_demo_acceptance"] == "OPEN"
    assert receipt["broker_connected"] is False
    assert receipt["orders_placed"] is False
    assert receipt["scenarios"][0]["real_broker_result"] == "NOT_RUN"
    assert json.loads((output / "receipt.json").read_text()) == receipt
    with pytest.raises(FileExistsError):
        harness.run(repo, candidate, output)
