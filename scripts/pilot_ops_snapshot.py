#!/usr/bin/env python3
"""Read-only, non-sensitive operational snapshot for a demo-only provider pilot.

This does not route alerts, establish uptime, place orders or clear G6/G9.
Admin credentials come only from process environment and never enter receipts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot_preflight import validate_backend_url  # noqa: E402

_SAFE_COUNTERS = {
    "pipeline": (
        "commands_pending", "commands_sent_to_ea",
        "commands_sent_to_ea_stale_60s", "commands_failed",
        "executions_failed", "management_failures",
    ),
    "assurance": (
        "reconciliation_conflicts", "execution_report_conflicts",
        "signal_replay_conflicts", "execution_reports_recovered",
    ),
    "tenancy": ("providers_total", "providers_paused", "feeds_total", "feeds_paused"),
}
_REVIEW_COUNTS = (
    ("pipeline", "commands_sent_to_ea_stale_60s"),
    ("assurance", "reconciliation_conflicts"),
    ("assurance", "execution_report_conflicts"),
    ("pipeline", "management_failures"),
)


def _read_object(response: httpx.Response) -> tuple[dict, bool]:
    if response.status_code != 200:
        return {}, False
    try:
        value = response.json()
    except ValueError:
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def collect(
    *, backend: str, admin_id: str, admin_api_key: str, candidate_sha: str,
) -> dict:
    backend = validate_backend_url(backend)
    if not admin_id or not admin_api_key:
        raise ValueError("Admin identity and API key must be set in environment")
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
        raise ValueError("Operator-declared candidate SHA must be 40 lowercase hex digits")

    with httpx.Client(base_url=backend, timeout=15, follow_redirects=False) as client:
        ready = client.get("/readyz")
        health = client.get("/health")
        metrics = client.get(
            "/admin/metrics",
            headers={"X-Admin-Id": admin_id, "X-Admin-API-Key": admin_api_key},
        )
    ready_data, ready_ok = _read_object(ready)
    health_data, health_ok = _read_object(health)
    metrics_data, metrics_ok = _read_object(metrics)

    checks = {
        "readiness": ready_ok and ready_data.get("status") == "ready",
        "health": health_ok and health_data.get("status") == "ok",
        "demo_only": health_ok and health_data.get("demo_only_mode") is True,
        "admin_auth": metrics_ok,
        "metrics_demo_only": metrics_ok
        and isinstance(metrics_data.get("mode"), dict)
        and metrics_data["mode"].get("demo_only") is True,
    }

    counters: dict[str, dict[str, int]] = {}
    for group, names in _SAFE_COUNTERS.items():
        source = metrics_data.get(group) if metrics_ok else None
        typed = isinstance(source, dict) and all(
            type(source.get(name)) is int and source[name] >= 0 for name in names
        )
        checks[f"{group}_counters"] = bool(typed)
        if typed:
            counters[group] = {name: source[name] for name in names}

    # These totals are cumulative. Nonzero is an operator review prompt,
    # not proof that a fresh incident occurred in this observation window.
    review = [
        {"group": group, "counter": key, "total": counters[group][key]}
        for group, key in _REVIEW_COUNTS
        if group in counters and counters[group][key] > 0
    ]
    valid = all(checks.values())
    result = "FAIL" if not valid else ("REVIEW_REQUIRED" if review else "COLLECTED")
    return {
        "schema": "signalgate-ops-snapshot-v1",
        "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin": backend,
        "candidate_sha_operator_declared": candidate_sha,
        "candidate_sha_verified_by_backend": False,
        "scope": "single_readonly_observation_not_slo_or_alerting",
        "result": result,
        "checks": checks,
        "counts": counters,
        "review_historical_totals": review,
        "http_status_codes": {
            "readyz": ready.status_code,
            "health": health.status_code,
            "admin_metrics": metrics.status_code,
        },
    }


def write_receipt(receipt: dict, output_root: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = output_root / f"{stamp}-OPS-{receipt['candidate_sha_operator_declared'][:12]}"
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = directory / "receipt.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(receipt, output, sort_keys=True, indent=2)
        output.write("\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/pilot-ops"))
    args = parser.parse_args()
    try:
        receipt = collect(
            backend=os.getenv("SIGNALGATE_BACKEND", ""),
            admin_id=os.getenv("SIGNALGATE_ADMIN_ID", ""),
            admin_api_key=os.getenv("SIGNALGATE_ADMIN_API_KEY", ""),
            candidate_sha=os.getenv("SIGNALGATE_CANDIDATE_SHA", ""),
        )
        path = write_receipt(receipt, args.output_root)
    except (ValueError, httpx.HTTPError, OSError) as exc:
        print(f"Observation incomplete: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    print(f"result={receipt['result']} receipt={path}")
    return 0 if receipt["result"] == "COLLECTED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
