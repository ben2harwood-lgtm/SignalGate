"""Scripted end-to-end demo against a RUNNING backend (no Telegram, no MT5).

Registers a user, creates a signal as admin, approves it, then runs the EA
simulator once to drive the full lifecycle. Useful for a one-command demo.

    python simulator/run_demo_flow.py \
        --backend http://127.0.0.1:8000 \
        --admin-id 123456789 \
        --api-key local-demo-ea-key

The --admin-id must be one of ADMIN_TELEGRAM_IDS in the backend .env.
"""
from __future__ import annotations

import argparse
import sys

import httpx

from ea_simulator import BANNER, EASimulator, validate_local_backend_origin

DEFAULT_SIGNAL = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def _confirmed_object(response, action: str) -> dict:
    """Require an accepted JSON object before any subsequent synthetic write."""
    if response.status_code != 200:
        raise RuntimeError(
            f"Scripted demo {action} was not accepted; stopping synthetic flow"
        )
    try:
        value = response.json()
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise RuntimeError(
            f"Scripted demo {action} returned no valid receipt; stopping synthetic flow"
        )
    return value


def _confirmed_identifier(receipt: dict, field: str, action: str) -> str:
    """Reject missing or malformed IDs rather than using them as route authority."""
    value = receipt.get(field)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(char in value for char in "/?#")
    ):
        raise RuntimeError(
            f"Scripted demo {action} returned no valid identifier; stopping synthetic flow"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalGate scripted demo flow")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-id", required=True, help="An ADMIN_TELEGRAM_IDS value")
    parser.add_argument("--api-key", default="local-demo-ea-key")
    parser.add_argument("--telegram-user-id", default="demo-tester-1")
    parser.add_argument("--signal", default=DEFAULT_SIGNAL)
    args = parser.parse_args()
    try:
        backend = validate_local_backend_origin(args.backend)
    except ValueError as exc:
        parser.error(str(exc))

    print(BANNER)
    # Synthetic approvals and fills must never be sent via an ambient proxy.
    with httpx.Client(
        base_url=backend, timeout=10.0, follow_redirects=False, trust_env=False
    ) as http:
        # 1. Validate demo health before ANY registration or fake execution.
        health_response = http.get("/health")
        try:
            health = health_response.json()
        except ValueError:
            health = None
        if (
            health_response.status_code != 200
            or not isinstance(health, dict)
            or health.get("status") != "ok"
            or health.get("demo_only_mode") is not True
            or health.get("admin_paused") is not False
        ):
            print("Refusing scripted demo: local backend did not confirm "
                  "active demo-only health.")
            sys.exit(1)
        print("Health:", health)

        # 2. Register tester.
        user = _confirmed_object(
            http.post(
                "/register_user",
                json={
                    "telegram_user_id": args.telegram_user_id,
                    "telegram_username": "demo",
                    "first_name": "Demo",
                },
            ),
            "registration",
        )
        user_id = _confirmed_identifier(user, "id", "registration")
        print("Registered user:", user_id)

        # 3. Create signal (admin).
        sig = _confirmed_object(
            http.post(
                "/signals/create",
                json={"raw_text": args.signal},
                headers={"X-Admin-Id": args.admin_id},
            ),
            "signal creation",
        )
        signal_id = _confirmed_identifier(sig, "id", "signal creation")
        print("Signal:", signal_id, sig.get("parser_status"), sig.get("parser_error") or "")
        if sig.get("parser_status") != "VALID":
            print("Signal rejected by parser; aborting.")
            sys.exit(1)

        # 4. Approve (YES).
        decision = _confirmed_object(
            http.post(
                f"/signals/{signal_id}/approve",
                json={"telegram_user_id": args.telegram_user_id},
            ),
            "signal approval",
        )
        if decision.get("result") != "APPROVED":
            print("Decision not approved; aborting scripted demo.")
            sys.exit(1)
        command_id = _confirmed_identifier(decision, "command_id", "signal approval")
        print("Decision: APPROVED ->", command_id)

        # 5. Simulate the EA lifecycle once.
        sim = EASimulator(http=http, user_id=user_id, api_key=args.api_key,
                          delay=0.3)
        if not sim.run_once(expected_command_id=command_id):
            print("No matching pending command found for simulator (unexpected).")
            sys.exit(1)

        print("\nDemo flow complete. Check /admin/status and logs for the ledger.")


if __name__ == "__main__":
    main()
