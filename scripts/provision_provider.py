#!/usr/bin/env python3
"""Provision a SignalGate Provider Edition tenant through the admin API.

The one-time provider credential is never printed to ordinary stdout by default.
Before any API mutation occurs, the operator must choose exactly one delivery
mode:

- --credential-output PATH: write one restrictive-permission JSON secret file;
- --show-secret: explicitly display the one-time secret in the terminal.

SignalGate stores only the provider credential hash, so losing the one-time raw
value requires rotation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def feed_create_payload(name: str, source_namespace: str) -> dict:
    """New provider feeds start paused until onboarding checks are complete."""
    return {
        "name": name,
        "source_namespace": source_namespace,
        "paused": True,
    }


def validate_credential_output(raw_path: str) -> Path:
    """Validate a new secret-file target before any remote provisioning."""
    path = Path(raw_path).expanduser()
    if path.exists():
        raise ValueError(f"credential output already exists: {path}")
    parent = path.parent if str(path.parent) else Path(".")
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"credential output parent does not exist: {parent}")
    return path


def credential_secret_record(provider: dict, credential: dict) -> dict:
    return {
        "schema": "signalgate-provider-credential-v1",
        "provider_id": provider["id"],
        "credential_id": credential["credential_id"],
        "label": credential.get("label"),
        "provider_api_key": credential["api_key"],
        "warning": (
            "One-time secret. Keep private. SignalGate stores only its one-way hash; "
            "rotate immediately if this file or value is exposed."
        ),
    }


def write_credential_secret(path: Path, record: dict) -> None:
    """Create, never overwrite, a best-effort owner-only secret file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows ACL semantics differ; the operator still explicitly chose the
        # local secret-file path and must deliver/store it through an approved channel.
        pass


def public_receipt(
    *,
    backend: str,
    org: dict,
    provider: dict,
    credential: dict,
    feed: dict,
    delivery_mode: str,
    credential_output: Path | None,
) -> dict:
    """Build a receipt that intentionally contains no raw credential."""
    delivery = {"mode": delivery_mode}
    if credential_output is not None:
        delivery["path"] = str(credential_output)
    return {
        "organization_id": org["id"],
        "provider_id": provider["id"],
        "credential_id": credential["credential_id"],
        "credential_label": credential.get("label"),
        "credential_delivery": delivery,
        "feed_id": feed["id"],
        "feed_paused": feed["paused"],
        "provider_portal": backend.rstrip("/") + "/provider-portal",
        "warning": (
            "Raw provider credential is intentionally excluded from this receipt. "
            "The new feed is paused; unpause only after source/subscriber/demo checks pass."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a SignalGate provider tenant")
    parser.add_argument(
        "--backend",
        default=os.getenv("SIGNALGATE_BACKEND", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--admin-id", default=os.getenv("SIGNALGATE_ADMIN_ID", ""))
    parser.add_argument("--admin-api-key", default=os.getenv("ADMIN_API_KEY", ""))
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--organization-slug", default="")
    parser.add_argument("--provider-name", required=True)
    parser.add_argument("--provider-slug", default="")
    parser.add_argument("--feed-name", default="Main Feed")
    parser.add_argument("--source-namespace", default="provider-main")
    delivery = parser.add_mutually_exclusive_group()
    delivery.add_argument(
        "--credential-output",
        default=os.getenv("SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT", ""),
        help=(
            "New file for the one-time credential. The file is created without overwrite "
            "and with owner-only mode where supported. Can also be set with "
            "SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT."
        ),
    )
    delivery.add_argument(
        "--show-secret",
        action="store_true",
        help="Explicitly print the one-time provider credential once to this terminal.",
    )
    args = parser.parse_args()

    if not args.admin_id:
        parser.error("--admin-id or SIGNALGATE_ADMIN_ID is required")
    if args.show_secret and args.credential_output:
        parser.error(
            "--show-secret cannot be combined with SIGNALGATE_PROVIDER_CREDENTIAL_OUTPUT"
        )
    if not args.show_secret and not args.credential_output:
        parser.error(
            "choose credential delivery before provisioning: "
            "--credential-output PATH (recommended) or --show-secret"
        )

    credential_output: Path | None = None
    if args.credential_output:
        try:
            credential_output = validate_credential_output(args.credential_output)
        except ValueError as exc:
            parser.error(str(exc))

    headers = {"X-Admin-Id": args.admin_id}
    if args.admin_api_key:
        headers["X-Admin-API-Key"] = args.admin_api_key

    org_slug = args.organization_slug or slug(args.organization_name)
    provider_slug = args.provider_slug or slug(args.provider_name)

    with httpx.Client(
        base_url=args.backend.rstrip("/"),
        timeout=15.0,
        headers=headers,
    ) as client:

        def post(path: str, payload: dict | None = None) -> dict:
            response = client.post(path, json=payload or {})
            if response.status_code >= 400:
                print(
                    f"Provisioning failed at {path}: {response.status_code} {response.text}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            return response.json()

        org = post(
            "/admin/organizations",
            {"name": args.organization_name, "slug": org_slug},
        )
        provider = post(
            "/admin/providers",
            {
                "organization_id": org["id"],
                "name": args.provider_name,
                "slug": provider_slug,
            },
        )
        credential = post(
            f"/admin/providers/{provider['id']}/credentials",
            {"label": "initial-onboarding"},
        )

        secret_record = credential_secret_record(provider, credential)
        if credential_output is not None:
            try:
                write_credential_secret(credential_output, secret_record)
            except OSError as exc:
                print(
                    "Credential was issued but could not be written to the selected secret "
                    f"file: {exc}. Rotate the provider credential before continuing.",
                    file=sys.stderr,
                )
                return 2
            print(
                f"One-time provider credential written to: {credential_output}",
                file=sys.stderr,
            )
        else:
            print(
                "Explicit --show-secret requested. The next JSON contains a one-time "
                "credential; do not retain terminal/session logs.",
                file=sys.stderr,
            )
            print(json.dumps(secret_record, indent=2))

        feed = post(
            f"/admin/providers/{provider['id']}/feeds",
            feed_create_payload(args.feed_name, args.source_namespace),
        )

    receipt = public_receipt(
        backend=args.backend,
        org=org,
        provider=provider,
        credential=credential,
        feed=feed,
        delivery_mode="file" if credential_output is not None else "stdout-explicit",
        credential_output=credential_output,
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
