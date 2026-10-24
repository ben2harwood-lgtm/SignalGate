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
# Only recognised operational feed ids enter receipts; unexpected backend text
# is excluded rather than being copied into a possibly shared evidence file.
FEED_ID_RE = re.compile(r"^FED-[A-Za-z0-9_-]{1,64}$")
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
    """Require an unambiguous API origin before supplying provider/admin keys.

    Both pilot_preflight and pilot_ops_snapshot call this before constructing
    their HTTP client. This is an operator input guard, not proof of the
    remote endpoint's identity, TLS configuration or pilot acceptance.
    """
    if (
        not raw
        or raw != raw.strip()
        or "\\" in raw
        or any(ord(char) <= 0x20 or ord(char) == 0x7f for char in raw)
    ):
        raise ValueError("backend must be a clean absolute URL")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("backend must be an absolute http(s) URL")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or "%" in parsed.netloc
    ):
        raise ValueError("credentials or ambiguous authority are forbidden")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("backend URL has an invalid port") from exc
    if (
        parsed.netloc.endswith(":")
        or parsed.path not in {"", "/"}
        or "?" in raw
        or "#" in raw
    ):
        raise ValueError("backend URL must be an origin without path, query or fragment")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("non-local pilot preflight requires HTTPS")
    return raw[:-1] if raw.endswith("/") else raw

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


def _object_json(response: httpx.Response) -> tuple[dict, bool]:
    """Do not treat HTTP 200 with malformed/non-object JSON as healthy."""
    if response.status_code != 200:
        return {}, False
    try:
        payload = response.json()
    except ValueError:
        return {}, False
    return (payload, True) if isinstance(payload, dict) else ({}, False)


def _object_list_json(response: httpx.Response) -> tuple[list[dict], bool]:
    if response.status_code != 200:
        return [], False
    try:
        payload = response.json()
    except ValueError:
        return [], False
    valid = isinstance(payload, list) and all(isinstance(item, dict) for item in payload)
    return (payload, True) if valid else ([], False)


def _nested_provider_id(payload: dict):
    provider = payload.get("provider")
    return provider.get("id") if isinstance(provider, dict) else None


# Only integer count fields from a provider export may be copied into a receipt.
# An unrecognised summary key may contain personal data or secret material.
_SAFE_SUMMARY_COUNTS = frozenset({
    "feed_count", "active_subscriber_count",
    "signal_count_in_export", "command_count_in_export",
})


def _safe_summary(payload: dict) -> dict:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return {}
    return {
        key: value
        for key, value in summary.items()
        if key in _SAFE_SUMMARY_COUNTS
        and isinstance(value, int) and not isinstance(value, bool)
        and value >= 0
    }


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

    # Do not let ambient proxy/CA environment settings redirect credentialled
    # operator traffic. The normal platform trust store is still used.
    with httpx.Client(
        base_url=backend, timeout=timeout, follow_redirects=False, trust_env=False
    ) as client:
        health = client.get("/health")
        health_json, health_valid = _object_json(health)
        _check("health", health_valid, f"HTTP {health.status_code}; object_json={health_valid}", checks)
        _check(
            "demo_only_mode",
            health_json.get("demo_only_mode") is True,
            f"demo_only_mode_is_true={health_json.get('demo_only_mode') is True}",
            checks,
        )
        admin_paused = health_json.get("admin_paused")
        admin_paused_typed = admin_paused is None or type(admin_paused) is bool
        _check(
            "health_metadata_types",
            admin_paused_typed,
            f"admin_paused_is_boolean_or_absent={admin_paused_typed}",
            checks,
        )
        evidence["admin_paused"] = admin_paused if type(admin_paused) is bool else None

        ready = client.get("/readyz")
        ready_json, ready_valid = _object_json(ready)
        _check(
            "readiness",
            ready_valid and ready_json.get("status") == "ready",
            f"HTTP {ready.status_code}; ready={ready_json.get('status') == 'ready'}",
            checks,
        )

        me = client.get("/providers/me", headers=headers)
        me_json, me_valid = _object_json(me)
        _check(
            "provider_auth",
            me_valid and me_json.get("id") == provider_id,
            f"HTTP {me.status_code}; provider_id_matches={me_json.get('id') == provider_id}",
            checks,
        )
        active = me_json.get("status") == "ACTIVE"
        _check("provider_active", me_valid and active, f"active={active}", checks)
        provider_paused = me_json.get("paused")
        provider_paused_typed = provider_paused is None or type(provider_paused) is bool
        _check(
            "provider_metadata_types",
            provider_paused_typed,
            f"provider_paused_is_boolean_or_absent={provider_paused_typed}",
            checks,
        )
        evidence["provider_status"] = "ACTIVE" if active else "INACTIVE_OR_UNKNOWN"
        evidence["provider_paused"] = provider_paused if type(provider_paused) is bool else None

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
        feeds_json, feeds_valid = _object_list_json(feeds)
        _check(
            "feed_list",
            feeds_valid,
            f"HTTP {feeds.status_code}; count={len(feeds_json) if isinstance(feeds_json, list) else 'invalid'}",
            checks,
        )
        if feeds_valid:
            evidence["feed_count"] = len(feeds_json)
            safe_ids = [
                row.get("id")
                for row in feeds_json
                if isinstance(row.get("id"), str)
                and FEED_ID_RE.fullmatch(row["id"])
            ]
            metadata_valid = len(safe_ids) == len(feeds_json) and all(
                type(row.get("paused")) is bool for row in feeds_json
            )
            _check(
                "feed_metadata_types",
                metadata_valid,
                f"valid_records={len(safe_ids)}; total={len(feeds_json)}; typed={metadata_valid}",
                checks,
            )
            evidence["feed_ids"] = safe_ids if metadata_valid else []
            if require_feeds_paused:
                all_paused = bool(feeds_json) and all(row.get("paused") is True for row in feeds_json)
                _check(
                    "feeds_paused_before_cohort",
                    all_paused,
                    f"all_paused={all_paused}; count={len(feeds_json)}",
                    checks,
                )

        overview = client.get("/providers/me/overview", headers=headers)
        overview_json, overview_valid = _object_json(overview)
        _check(
            "provider_overview",
            overview_valid
            and _nested_provider_id(overview_json) == provider_id,
            f"HTTP {overview.status_code}",
            checks,
        )
        invalid_overview_counts = 0
        for field in (
            "feed_count",
            "active_subscribers",
            "active_accounts",
            "signal_count",
            "command_count",
        ):
            if field in overview_json:
                value = overview_json[field]
                if type(value) is int and value >= 0:
                    evidence[field] = value
                else:
                    invalid_overview_counts += 1
        _check(
            "overview_count_types",
            invalid_overview_counts == 0,
            f"invalid_count_fields={invalid_overview_counts}",
            checks,
        )

        export = client.get("/providers/me/export", headers=headers)
        export_json, export_valid = _object_json(export)
        forbidden = find_forbidden_keys(export_json) if export_valid else []
        _check(
            "provider_export",
            export_valid
            and _nested_provider_id(export_json) == provider_id,
            f"HTTP {export.status_code}",
            checks,
        )
        _check(
            "provider_export_secret_fields_absent",
            export_valid and not forbidden,
            f"forbidden_key_count={len(forbidden)}",
            checks,
        )
        if export_valid:
            evidence["provider_export_sha256"] = _sha256_json(export_json)
            evidence["provider_export_summary"] = _safe_summary(export_json)

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


def _write_receipt_owner_only(path: Path, content: str) -> None:
    """Create a new receipt with owner-only permissions regardless of umask."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def write_receipt(receipt: dict, evidence_root: Path) -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = evidence_root / f"{stamp}-PILOT-PREFLIGHT-{receipt['declared_candidate_sha'][:12]}"
    target.mkdir(mode=0o700, parents=True, exist_ok=False)

    _write_receipt_owner_only(
        target / "receipt.json",
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
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
    _write_receipt_owner_only(target / "receipt.md", "\n".join(lines))
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
        # Transport errors and exception messages can carry private URLs,
        # response bodies, file paths or credentials; never echo them to logs.
        print(
            f"preflight error ({type(exc).__name__}): operation failed; "
            "exception details withheld to protect private data",
            file=sys.stderr,
        )
        return 2

    print(f"result={receipt['result']}")
    print(f"receipt={target}")
    return 0 if receipt["result"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
