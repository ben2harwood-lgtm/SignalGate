#!/usr/bin/env python3
"""Replay fabricated backend reports against an exact Git candidate, without MT5.

This tool never starts a terminal or connects to a broker. Its receipt cannot
close the actual demo-account acceptance gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
import zipfile

# Each row separates actual Python API exercises from static MQL source checks.
SCENARIOS = (
    ("market_fill", "synthetic_api", "tests/test_simulator.py::test_full_simulator_flow"),
    ("symbol_suffix", "source_only", "tests/test_ea_source_safety.py::test_ea_resolves_broker_symbol_suffix_and_netting_fallback"),
    ("limit_refusal", "source_only", "tests/test_ea_source_safety.py::test_ea_rejects_limit_and_verifies_broker_fill_retcode"),
    ("broker_rejection", "synthetic_api", "tests/test_commands.py::test_execution_failed_recorded"),
    ("stop_loss", "synthetic_api", "tests/test_simulator.py::test_simulator_stop_out_records_loss"),
    ("manual_close", "synthetic_api", "tests/test_provider_demo_rehearsal.py::test_provider_consent_recovery_manual_close_and_evidence"),
    ("netting_fallback", "source_only", "tests/test_ea_source_safety.py::test_ea_resolves_broker_symbol_suffix_and_netting_fallback"),
    ("lost_callback", "synthetic_api", "tests/test_commands.py::test_broker_snapshot_recovers_lost_execution_callback"),
    ("restart_poll_gate", "source_only", "tests/test_ea_source_safety.py::test_ea_continuously_reconciles_open_broker_positions"),
    ("snapshot_conflict", "synthetic_api", "tests/test_commands.py::test_broker_snapshot_conflict_fails_closed_and_is_audited"),
)
EXTRA_TESTS = (
    "tests/test_commands.py::test_hosted_reconciliation_is_bound_to_owning_license",
    "tests/test_commands.py::test_open_snapshot_cannot_override_failed_execution",
    "tests/test_commands.py::test_duplicate_execution_report_is_idempotent",
    "tests/test_commands.py::test_late_event_cannot_regress_terminal_command",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junit_result(path: Path, expected: list[str]) -> dict:
    """A zero exit code alone is insufficient: require every named test, no skips."""
    try:
        report_bytes = path.read_bytes()
        root = ET.fromstring(report_bytes, forbid_dtd=True)
        cases = list(root.iter("testcase"))
    except (OSError, ET.ParseError, DefusedXmlException):
        return {"passed": False, "reason": "Missing or invalid JUnit evidence"}
    expected_names = {node.split("::", 1)[1] for node in expected}
    names = [case.get("name") for case in cases]
    passed = (
        len(names) == len(expected_names) and set(names) == expected_names
        and all(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases)
        and not list(root.iter("error"))
    )
    return {"passed": passed, "test_count": len(cases), "expected_test_count": len(expected_names),
            "sha256": hashlib.sha256(report_bytes).hexdigest()}


def run(repo: Path, candidate: str, output: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("--candidate-sha must be the full lowercase 40-character Git SHA")
    actual = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{candidate}^{{commit}}"],
                            check=True, capture_output=True, text=True).stdout.strip()
    if actual != candidate:
        raise ValueError("Candidate did not resolve to the exact requested commit")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    tests = list(dict.fromkeys([row[2] for row in SCENARIOS] + list(EXTRA_TESTS)))
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="signalgate-broker-free-") as temporary:
        scratch = Path(temporary)
        archive = scratch / "candidate.zip"
        subprocess.run(["git", "-C", str(repo), "archive", "--format=zip", "-o", str(archive), candidate], check=True)
        source = scratch / "source"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(source)
            snapshot_files = [name for name in bundle.namelist() if not name.endswith("/")]
        def source_fingerprint() -> str:
            manifest = {name: sha256(source / name) for name in snapshot_files}
            return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        fingerprint_before = source_fingerprint()
        ea_hash_before = sha256(source / "mt5_ea/SignalGateEA.mq5")
        env = os.environ.copy()
        env.update({"SIGNALGATE_TEST_DATABASE_URL": f"sqlite:///{scratch / 'rehearsal.db'}",
                    "DATABASE_URL": f"sqlite:///{scratch / 'rehearsal.db'}",
                    "DEMO_ONLY_MODE": "true", "REQUIRE_LICENSE": "false",
                    "TELEGRAM_BOT_TOKEN": "", "ADMIN_API_KEY": "",
                    "REGISTRATION_API_KEY": "", "SIGNAL_PROVIDER_API_KEY": "",
                    "ALLOWED_SYMBOLS": "", "SIGNAL_EXTRACTOR": "fake"})
        command = [sys.executable, "-m", "pytest", "-q", *tests,
                   f"--junitxml={output / 'rehearsal-junit.xml'}"]
        with (output / "rehearsal.log").open("w") as log:
            result = subprocess.run(command, cwd=source / "backend", env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=180)
        junit = junit_result(output / "rehearsal-junit.xml", tests)
        fingerprint_after = source_fingerprint()
        source_stable = fingerprint_before == fingerprint_after
        passed = result.returncode == 0 and junit["passed"] and source_stable
        receipt = {
            "schema": "signalgate-broker-free-rehearsal-v1",
            "candidate_sha": candidate,
            "candidate_ea_source_sha256": ea_hash_before,
            "source_fingerprint_before": fingerprint_before,
            "source_fingerprint_after": fingerprint_after,
            "source_stable": source_stable,
            "harness_sha256": sha256(Path(__file__)),
            "started_at_utc": started,
            "completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "evidence_class": "synthetic_backend_and_static_source_only",
            "broker_connected": False, "orders_placed": False,
            "actual_mt5_demo_acceptance": "OPEN",
            "result": "REHEARSAL_PASS" if passed else "REHEARSAL_FAIL",
            "pytest_exit_code": result.returncode, "junit": junit,
            "scenarios": [{"scenario": name, "rehearsal_evidence": kind,
                           "test": test, "real_broker_result": "NOT_RUN"}
                          for name, kind, test in SCENARIOS],
            "additional_tests": list(EXTRA_TESTS),
            "artifacts": {"rehearsal.log": sha256(output / "rehearsal.log"),
                          "rehearsal-junit.xml": junit.get("sha256")},
        }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = run(Path(__file__).resolve().parents[1], args.candidate_sha, args.output.resolve())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Rehearsal not completed: {exc}\n")
    print(f"{receipt['result']}: synthetic evidence only; actual MT5 demo acceptance OPEN")
    return 0 if receipt["result"] == "REHEARSAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
