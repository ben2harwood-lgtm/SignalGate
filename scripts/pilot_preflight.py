#!/usr/bin/env python3
"""Read-only SignalGate Provider Edition pilot preflight.

The script deliberately performs no state-changing requests. Provider/API secrets
are read from environment variables only and are never written to the receipt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_EXPORT_KEYS = {
    "api_key",
    "provider_api_key",
    "key_hash",
    "license_key",
    "license_key_hash",
    "token_hash",
    "invite_token",
    "connection_token",
    "raw_text",
}


def validate_backend_url(raw: str) -> str:
    value = raw.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("backend must be an absolute http(s) URL")
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not local and parsed.scheme != "https":
        raise ValueError("non-local pilot preflight requires HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in the backend URL")
    if parsed.query or parsed.fragment:
        raise ValueError("backend URL must not contain a query or fragment")
    return value


def mutate_secret(value: str) -> str:
    if not value:
        raise ValueError("provider API key is required")
    tail = "x" if value[-1:] != "x" else "y"
    return value[:-1] + tail if len(value) > 1 else tail


def find_forbidden_keys(value, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            here = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_EXPORT_KEYS:
                hits.append(here)
            hits.extend(find_forbidden_keys(item, here))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            hits.extend(find_forbidden_keys(item, f"{path}[{idx}]"))
    return hits


def _sha256_json(value) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _check(name: str, passed: bool, detail: str, checks: list[dict]) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def run_preflight(
    *,
    backend: str,
    provider_id: str,
    provider_api_key: str,
    declared_candidate_sha: str,
    require_feeds_paused: bool,
    timeout: float = 15.0,
) -> dict:
    backend = validate_backend_url(backend)
    if not provider_id:
        raise ValueError("provider id is required")
    if not provider_api_key:
        raise ValueError("provider API key is required")
    if not SHA_RE.fullmatch(declared_candidate_sha):
        raise ValueError("declared candidate SHA must be exact lowercase 40-char hex")

    headers = {
        "X-Provider-Id": provider_id,
        "X-Provider-API-Key": provider_api_key,
    }
    checks: list[dict] = []
    evidence: dict = {}

    with httpx.Client(base_url=backend, timeout=timeout, follow_redirects=False) as client:
        health = client.get("/health")
        health_json = health.json() if health.status_code == 200 else {}
        _check("health", health.status_code == 200, f"HTTP {health.status_code}", checks)
        _check(
            "demo_only_mode",
            health_json.get("demo_only_mode") is True,
            f"demo_only_mode={health_json.get('demo_only_mode')!r}",
            checks,
        )
        evidence["admin_paused"] = health_json.get("admin_paused")

        ready = client.get("/readyz")
        ready_json = ready.json() if ready.status_code == 200 else {}
        _check(
            "readiness",
            ready.status_code == 200 and ready_json.get("status") == "ready",
            f"HTTP {ready.status_code}; status={ready_json.get('status')!r}",
            checks,
        )

        me = client.get("/providers/me", headers=headers)
        me_json = me.json() if me.status_code == 200 else {}
        _check(
            "provider_auth",
            me.status_code == 200 and me_json.get("id") == provider_id,
            f"HTTP {me.status_code}; provider_id={me_json.get('id')!r}",
            checks,
        )
        evidence["provider_status"] = me_json.get("status")
        evidence["provider_paused"] = me_json.get("paused")

        wrong_headers = {
            "X-Provider-Id": provider_id,
            "X-Provider-API-Key": mutate_secret(provider_api_key),
        }
        wrong = client.get("/providers/me", headers=wrong_headers)
        _check(
            "wrong_provider_key_rejected",
            wrong.status_code == 401,
            f"HTTP {wrong.status_code}",
            checks,
        )

        feeds = client.get("/providers/me/feeds", headers=headers)
        feeds_json = feeds.json() if feeds.status_code == 200 else []
        _check(
            "feed_list",
            feeds.status_code == 200 and isinstance(feeds_json, list),
            f"HTTP {feeds.status_code}; count={len(feeds_json) if isinstance(feeds_json, list) else 'invalid'}",
            checks,
        )
        if isinstance(feeds_json, list):
            evidence["feed_count"] = len(feeds_json)
            evidence["feed_ids"] = [row.get("id") for row in feeds_json]
            if require_feeds_paused:
                all_paused = bool(feeds_json) and all(row.get("paused") is True for row in feeds_json)
                _check(
                    "feeds_paused_before_cohort",
                    all_paused,
                    f"paused={[(row.get('id'), row.get('paused')) for row in feeds_json]}",
                    checks,
                )

        overview = client.get("/providers/me/overview", headers=headers)
        overview_json = overview.json() if overview.status_code == 200 else {}
        _check(
            "provider_overview",
            overview.status_code == 200
            and overview_json.get("provider", {}).get("id") == provider_id,
            f"HTTP {overview.status_code}",
            checks,
        )
        for field in (
            "feed_count",
            "active_subscribers",
            "active_accounts",
            "signal_count",
            "command_count",
        ):
            if field in overview_json:
                evidence[field] = overview_json[field]

        export = client.get("/providers/me/export", headers=headers)
        export_json = export.json() if export.status_code == 200 else {}
        forbidden = find_forbidden_keys(export_json) if export.status_code == 200 else []
        _check(
            "provider_export",
            export.status_code == 200
            and export_json.get("provider", {}).get("id") == provider_id,
            f"HTTP {export.status_code}",
            checks,
        )
        _check(
            "provider_export_secret_fields_absent",
            export.status_code == 200 and not forbidden,
            "none" if not forbidden else ", ".join(forbidden[:20]),
            checks,
        )
        if export.status_code == 200:
            evidence["provider_export_sha256"] = _sha256_json(export_json)
            evidence["provider_export_summary"] = export_json.get("summary", {})

    passed = all(item["passed"] for item in checks)
    return {
        "schema": "signalgate-provider-pilot-preflight-v1",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "backend_origin": backend,
        "provider_id": provider_id,
        "declared_candidate_sha": declared_candidate_sha,
        "candidate_sha_verified_by_backend": False,
        "require_feeds_paused": require_feeds_paused,
        "result": "PASS" if passed else "FAIL",
        "checks": checks,
        "evidence": evidence,
        "note": (
            "No secret values or raw provider export are stored. "
            "The candidate SHA is operator-declared because RC2 does not expose a deployment build-id endpoint."
        ),
    }


def write_receipt(receipt: dict, evidence_root: Path) -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = evidence_root / f"{stamp}-PILOT-PREFLIGHT-{receipt['declared_candidate_sha'][:12]}"
    target.mkdir(parents=True, exist_ok=False)

    (target / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# SignalGate Provider Pilot Preflight",
        "",
        f"- Result: **{receipt['result']}**",
        f"- Backend: {receipt['backend_origin']}",
        f"- Provider id: {receipt['provider_id']}",
        f"- Declared candidate SHA: {receipt['declared_candidate_sha']}",
        "- Candidate SHA verified by backend: **no** (operator-declared for RC2)",
        "",
        "## Checks",
        "",
    ]
    for row in receipt["checks"]:
        mark = "PASS" if row["passed"] else "FAIL"
        lines.append(f"- **{mark}** — {row['name']}: {row['detail']}")
    lines += [
        "",
        "This receipt contains no provider API key, customer licence, invite token, raw signal text, or raw provider export.",
        "",
    ]
    (target / "receipt.md").write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SignalGate provider pilot preflight")
    parser.add_argument(
        "--backend",
        default=os.getenv("SIGNALGATE_BACKEND", ""),
        help="Backend origin; defaults to SIGNALGATE_BACKEND.",
    )
    parser.add_argument(
        "--provider-id",
        default=os.getenv("SIGNALGATE_PROVIDER_ID", ""),
        help="Provider id; defaults to SIGNALGATE_PROVIDER_ID.",
    )
    parser.add_argument(
        "--candidate-sha",
        default=os.getenv("SIGNALGATE_CANDIDATE_SHA", ""),
        help="Expected/deployed candidate SHA as declared by the operator.",
    )
    parser.add_argument(
        "--allow-unpaused",
        action="store_true",
        help="Do not require every provider feed to still be paused.",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("artifacts/pilot-preflight"),
    )
    args = parser.parse_args()

    provider_api_key = os.getenv("SIGNALGATE_PROVIDER_API_KEY", "")
    if not provider_api_key:
        parser.error(
            "SIGNALGATE_PROVIDER_API_KEY must be set in the environment; "
            "it is never accepted on the command line"
        )

    try:
        receipt = run_preflight(
            backend=args.backend,
            provider_id=args.provider_id,
            provider_api_key=provider_api_key,
            declared_candidate_sha=args.candidate_sha,
            require_feeds_paused=not args.allow_unpaused,
        )
        target = write_receipt(receipt, args.evidence_root)
    except (ValueError, httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
        print(f"preflight error: {exc}", file=sys.stderr)
        return 2

    print(f"result={receipt['result']}")
    print(f"receipt={target}")
    return 0 if receipt["result"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
