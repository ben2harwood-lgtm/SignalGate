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

from ea_simulator import BANNER, EASimulator

DEFAULT_SIGNAL = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalGate scripted demo flow")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-id", required=True, help="An ADMIN_TELEGRAM_IDS value")
    parser.add_argument("--api-key", default="local-demo-ea-key")
    parser.add_argument("--telegram-user-id", default="demo-tester-1")
    parser.add_argument("--signal", default=DEFAULT_SIGNAL)
    args = parser.parse_args()

    print(BANNER)
    with httpx.Client(base_url=args.backend, timeout=10.0) as http:
        # 1. Health.
        health = http.get("/health").json()
        print("Health:", health)
        if health.get("admin_paused"):
            print("Backend is paused; resume before running the demo.")
            sys.exit(1)

        # 2. Register tester.
        user = http.post(
            "/register_user",
            json={
                "telegram_user_id": args.telegram_user_id,
                "telegram_username": "demo",
                "first_name": "Demo",
            },
        ).json()
        print("Registered user:", user["id"])

        # 3. Create signal (admin).
        sig = http.post(
            "/signals/create",
            json={"raw_text": args.signal},
            headers={"X-Admin-Id": args.admin_id},
        ).json()
        print("Signal:", sig["id"], sig["parser_status"], sig.get("parser_error") or "")
        if sig["parser_status"] != "VALID":
            print("Signal rejected by parser; aborting.")
            sys.exit(1)

        # 4. Approve (YES).
        decision = http.post(
            f"/signals/{sig['id']}/approve",
            json={"telegram_user_id": args.telegram_user_id},
        ).json()
        print("Decision:", decision["result"], "->", decision.get("command_id"))
        if decision["result"] != "APPROVED":
            sys.exit(1)

        # 5. Simulate the EA lifecycle once.
        sim = EASimulator(http=http, user_id=user["id"], api_key=args.api_key,
                          delay=0.3)
        if not sim.run_once():
            print("No pending command found for simulator (unexpected).")
            sys.exit(1)

        print("\nDemo flow complete. Check /admin/status and logs for the ledger.")


if __name__ == "__main__":
    main()
