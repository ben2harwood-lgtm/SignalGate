#!/usr/bin/env python3
"""Provision a SignalGate Provider Edition tenant through the admin API.

Prints the provider credential exactly once in the final JSON receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a SignalGate provider tenant")
    parser.add_argument("--backend", default=os.getenv("SIGNALGATE_BACKEND", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-id", default=os.getenv("SIGNALGATE_ADMIN_ID", ""))
    parser.add_argument("--admin-api-key", default=os.getenv("ADMIN_API_KEY", ""))
    parser.add_argument("--organization-name", required=True)
    parser.add_argument("--organization-slug", default="")
    parser.add_argument("--provider-name", required=True)
    parser.add_argument("--provider-slug", default="")
    parser.add_argument("--feed-name", default="Main Feed")
    parser.add_argument("--source-namespace", default="provider-main")
    args = parser.parse_args()

    if not args.admin_id:
        parser.error("--admin-id or SIGNALGATE_ADMIN_ID is required")

    headers = {"X-Admin-Id": args.admin_id}
    if args.admin_api_key:
        headers["X-Admin-API-Key"] = args.admin_api_key

    org_slug = args.organization_slug or slug(args.organization_name)
    provider_slug = args.provider_slug or slug(args.provider_name)

    with httpx.Client(base_url=args.backend.rstrip("/"), timeout=15.0, headers=headers) as client:
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
        feed = post(
            f"/admin/providers/{provider['id']}/feeds",
            feed_create_payload(args.feed_name, args.source_namespace),
        )

    receipt = {
        "organization_id": org["id"],
        "provider_id": provider["id"],
        "provider_api_key": credential["api_key"],
        "feed_id": feed["id"],
        "feed_paused": feed["paused"],
        "provider_portal": args.backend.rstrip("/") + "/provider-portal",
        "warning": (
            "Store provider_api_key now; SignalGate stores only its one-way hash. "
            "The new feed is paused; unpause only after source/subscriber/demo checks pass."
        ),
    }
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
