"""One-command engine dry-run for a quick demo (no Telegram, no MetaTrader).

This proves the whole backend + execution + ledger pipeline in one go and prints
the honest record at the end — a WIN and a LOSS, side by side — so you can eyeball
that the system records losses as losses before showing anyone.

    python simulator/quick_demo.py --admin-id 123456789 --api-key local-demo-ea-key

This is NOT the Telegram demo Nick drives. It's the confidence check you run first:
it bypasses Telegram and MT5 and uses the simulator to drive two full lifecycles.
For Nick's live walkthrough (screenshots -> cards -> YES), start the bot and follow
docs/DEMO_DAY_RUNBOOK.md.

Requires the backend to be running:
    cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import argparse
import sys

import httpx

from ea_simulator import BANNER, EASimulator

WIN_SIGNAL = "XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363"
LOSS_SIGNAL = "EURUSD SELL SL 1.0950 TP1 1.0900 TP2 1.0850 TP3 1.0800"


def _run_one(http: httpx.Client, admin_id: str, api_key: str, tester: str,
             raw_text: str, scenario: str) -> None:
    sig = http.post(
        "/signals/create",
        json={"raw_text": raw_text},
        headers={"X-Admin-Id": admin_id},
    ).json()
    print(f"  signal {sig['id']}: {sig['parser_status']} {sig.get('parser_error') or ''}")
    if sig["parser_status"] != "VALID":
        print("  parser rejected — skipping")
        return
    dec = http.post(
        f"/signals/{sig['id']}/approve", json={"telegram_user_id": tester}
    ).json()
    print(f"  approval: {dec['result']} -> {dec.get('command_id')}")
    if dec["result"] != "APPROVED":
        return
    user = http.get(f"/users/{tester}").json()
    sim = EASimulator(http=http, user_id=user["id"], api_key=api_key,
                      delay=0.2, scenario=scenario)
    sim.run_once()


def _print_ledger(http: httpx.Client, admin_id: str) -> None:
    body = http.get(
        "/admin/ledger", params={"limit": 20}, headers={"X-Admin-Id": admin_id}
    ).json()
    rows = body.get("ledger", [])
    print("\n================ PERFORMANCE LEDGER (the honest record) ================")
    print(f"  {'ID':11} {'SYMBOL':7} {'DIR':4} {'RESULT':16} {'R':>6}")
    print("  " + "-" * 52)
    for r in rows:
        rres = r.get("r_result")
        rstr = f"{rres:+.1f}" if isinstance(rres, (int, float)) else "-"
        print(f"  {r['id']:11} {str(r.get('symbol')):7} "
              f"{str(r.get('direction')):4} {r.get('result_status',''):16} {rstr:>6}")
    print("  " + "-" * 52)
    print("  Losses show as losses. Nothing is hidden — that is the whole point.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalGate quick engine dry-run")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-id", required=True, help="An ADMIN_TELEGRAM_IDS value")
    parser.add_argument("--api-key", default="local-demo-ea-key")
    parser.add_argument("--tester", default="quick-demo-tester")
    args = parser.parse_args()

    print(BANNER)
    with httpx.Client(base_url=args.backend, timeout=10.0) as http:
        try:
            health = http.get("/health").json()
        except httpx.HTTPError:
            print(f"Backend not reachable at {args.backend}.")
            print("Start it first:  cd backend && "
                  ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000")
            sys.exit(1)
        print("Health:", health)
        if health.get("admin_paused"):
            print("Backend is paused; run /resume (or POST /admin/resume) first.")
            sys.exit(1)

        http.post("/register_user", json={
            "telegram_user_id": args.tester,
            "telegram_username": "quickdemo",
            "first_name": "QuickDemo",
        })

        print("\n[1/2] WINNING trade (reaches TP3):")
        _run_one(http, args.admin_id, args.api_key, args.tester, WIN_SIGNAL, "win")

        print("\n[2/2] LOSING trade (stopped out):")
        _run_one(http, args.admin_id, args.api_key, args.tester, LOSS_SIGNAL, "stop_out")

        _print_ledger(http, args.admin_id)
        print("Done. To show it in a browser during the demo, open:")
        print(f"  {args.backend}/admin/ledger   (send header X-Admin-Id: {args.admin_id})")


if __name__ == "__main__":
    main()
