"""SignalGate EA SIMULATOR (NOT a real trader).

================================ SIMULATOR ONLY ================================
This program imitates the MetaTrader 5 Expert Advisor for local end-to-end
testing of the backend + Telegram flow WITHOUT MetaTrader installed.

It does NOT connect to any broker and places NO trades of any kind, demo or
live. It simply polls the backend for an approved command, acknowledges it,
and posts fake-but-structured execution + management events so the full
lifecycle can be exercised and recorded in the performance ledger.
==============================================================================
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, List, Optional, Protocol

import httpx


BANNER = (
    "================ SignalGate EA SIMULATOR (NOT REAL TRADING) ================\n"
    " This is a simulator. No broker connection. No trades are placed.\n"
    " It only posts fake execution/management events to the backend for testing.\n"
    "===========================================================================\n"
)


class HttpLike(Protocol):
    """Minimal interface satisfied by both httpx.Client and FastAPI TestClient."""

    def get(self, url: str, **kwargs) -> Any: ...
    def post(self, url: str, **kwargs) -> Any: ...


def _fake_ticket(base: int, offset: int) -> str:
    # Deterministic pseudo ticket numbers for the simulator.
    return str(base + offset)


class EASimulator:
    """Polls the backend and simulates the EA lifecycle for one user."""

    def __init__(
        self,
        http: HttpLike,
        user_id: str,
        api_key: str,
        delay: float = 0.5,
        verbose: bool = True,
    ) -> None:
        self.http = http
        self.user_id = user_id
        self.headers = {"X-EA-API-Key": api_key}
        self.delay = delay
        self.verbose = verbose
        self.processed: set = set()  # local idempotency, like the real EA

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[SIMULATOR] {msg}")

    def _sleep(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    # --- backend calls ----------------------------------------------------

    def poll(self) -> Optional[Dict[str, Any]]:
        resp = self.http.get(
            "/commands/pending",
            params={"user_id": self.user_id},
            headers=self.headers,
        )
        data = resp.json()
        return data.get("command")

    def ack_received(self, command_id: str) -> None:
        self.http.post(
            f"/commands/{command_id}/received", json={}, headers=self.headers
        )

    def post_execution(self, command: Dict[str, Any], child_tickets: List[str]) -> None:
        # Simulate a small favourable entry near the implied entry.
        entry = command.get("entry_price")
        executed_price = entry if entry is not None else _implied_entry(command)
        payload = {
            "status": "SUCCESS",
            "broker_ticket": child_tickets[0] if child_tickets else None,
            "child_tickets_json": json.dumps(child_tickets),
            "executed_symbol": command["symbol"],
            "executed_direction": command["direction"],
            "requested_price": entry,
            "executed_price": executed_price,
            "lot_size": sum(
                tp.get("lot") or 0 for tp in command["take_profits"]
            ) or command["lot_size"],
            "initial_stop_loss": command["initial_stop_loss"],
            "tp1": _tp_price(command, 1),
            "tp2": _tp_price(command, 2),
            "tp3": _tp_price(command, 3),
            "spread_at_execution": 20,
            "slippage": 0,
        }
        self.http.post(
            f"/commands/{command['command_id']}/execution",
            json=payload,
            headers=self.headers,
        )

    def post_event(self, command_id: str, **fields) -> None:
        self.http.post(
            f"/commands/{command_id}/management_event",
            json=fields,
            headers=self.headers,
        )

    # --- lifecycle --------------------------------------------------------

    def simulate_lifecycle(self, command: Dict[str, Any]) -> None:
        """Simulate open -> TP1 -> BE -> TP2 -> SL@TP1 -> TP3 -> fully closed."""
        cid = command["command_id"]
        base_ticket = 100000

        # Open child tickets (split-ticket demo mode) or single ticket.
        if command.get("split_ticket_demo_partial_mode"):
            child_tickets = [_fake_ticket(base_ticket, i) for i in range(3)]
        else:
            child_tickets = [_fake_ticket(base_ticket, 0)]

        self.log(f"Simulating OPEN for {cid} tickets={child_tickets}")
        self.post_execution(command, child_tickets)
        self.post_event(
            cid,
            broker_ticket=child_tickets[0],
            event_type="OPENED",
            stage="OPENED",
            result="SUCCESS",
            price=_implied_entry(command),
        )
        self._sleep()

        entry = _implied_entry(command)
        sl = command["initial_stop_loss"]

        # TP1
        self.log("Simulating TP1 reached + close + SL->breakeven")
        self.post_event(cid, event_type="TP1_REACHED", stage="OPENED",
                        result="SUCCESS", price=_tp_price(command, 1))
        self.post_event(cid, broker_ticket=child_tickets[0],
                        event_type="TP1_CLOSE_SUCCESS", stage="TP1_DONE",
                        result="SUCCESS", price=_tp_price(command, 1),
                        lot_size_before=command["take_profits"][0].get("lot"),
                        lot_size_after=0)
        self.post_event(cid, event_type="SL_MOVE_BREAKEVEN_SUCCESS",
                        stage="TP1_DONE", requested_action="MOVE_SL_BREAKEVEN",
                        result="SUCCESS", stop_loss_before=sl, stop_loss_after=entry)
        self._sleep()

        if _tp_price(command, 2) is not None:
            # TP2
            self.log("Simulating TP2 reached + close + SL->TP1")
            self.post_event(cid, event_type="TP2_REACHED", stage="TP1_DONE",
                            result="SUCCESS", price=_tp_price(command, 2))
            self.post_event(cid, broker_ticket=child_tickets[min(1, len(child_tickets)-1)],
                            event_type="TP2_CLOSE_SUCCESS", stage="TP2_DONE",
                            result="SUCCESS", price=_tp_price(command, 2))
            self.post_event(cid, event_type="SL_MOVE_TP1_SUCCESS", stage="TP2_DONE",
                            requested_action="MOVE_SL_TP1", result="SUCCESS",
                            stop_loss_before=entry, stop_loss_after=_tp_price(command, 1))
            self._sleep()

        if _tp_price(command, 3) is not None:
            # TP3
            self.log("Simulating TP3 reached + final close")
            self.post_event(cid, event_type="TP3_REACHED", stage="TP2_DONE",
                            result="SUCCESS", price=_tp_price(command, 3))
            self.post_event(cid, broker_ticket=child_tickets[-1],
                            event_type="TP3_CLOSE_SUCCESS", stage="TP3_DONE",
                            result="SUCCESS", price=_tp_price(command, 3))
            self._sleep()

        # Fully closed
        self.log("Simulating FULLY_CLOSED")
        self.post_event(cid, event_type="FULLY_CLOSED", stage="FULLY_CLOSED",
                        result="SUCCESS")

    def run_once(self) -> bool:
        """Poll once; if a command is found, run its full lifecycle.

        Returns True if a command was processed.
        """
        command = self.poll()
        if command is None:
            return False
        cid = command["command_id"]
        if cid in self.processed:
            self.log(f"DUPLICATE_COMMAND {cid} ignored (local idempotency).")
            return False
        self.processed.add(cid)
        self.log(f"Received command {cid} ({command['symbol']} {command['direction']})")
        self.ack_received(cid)
        self.simulate_lifecycle(command)
        self.log(f"Command {cid} lifecycle complete (FULLY_CLOSED).")
        return True

    def run_forever(self, poll_interval: float = 2.0) -> None:
        self.log(f"Polling {self.user_id} every {poll_interval}s. Ctrl+C to stop.")
        try:
            while True:
                processed = self.run_once()
                if not processed:
                    time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.log("Stopped by user.")


# --- helpers --------------------------------------------------------------

def _tp_price(command: Dict[str, Any], level: int) -> Optional[float]:
    for tp in command.get("take_profits", []):
        if tp.get("level") == level:
            return tp.get("price")
    return None


def _implied_entry(command: Dict[str, Any]) -> float:
    """Pick a plausible entry for a MARKET order in the simulator.

    Uses the explicit entry price if present, else a point just on the
    profitable side of the stop loss toward TP1.
    """
    if command.get("entry_price") is not None:
        return command["entry_price"]
    sl = command["initial_stop_loss"]
    tp1 = _tp_price(command, 1)
    if tp1 is None:
        return sl
    # Entry roughly 20% of the way from SL toward TP1.
    return round(sl + (tp1 - sl) * 0.2, 5)


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalGate EA SIMULATOR (no trading)")
    parser.add_argument("--user-id", required=True, help="e.g. USER-000001")
    parser.add_argument("--api-key", default="local-demo-ea-key")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Delay between simulated lifecycle events (seconds)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Process a single command then exit (immediate mode)",
    )
    args = parser.parse_args()

    print(BANNER)
    with httpx.Client(base_url=args.backend, timeout=10.0) as http:
        sim = EASimulator(
            http=http,
            user_id=args.user_id,
            api_key=args.api_key,
            delay=args.delay,
        )
        if args.once:
            if not sim.run_once():
                sim.log("No pending command found.")
        else:
            sim.run_forever(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
