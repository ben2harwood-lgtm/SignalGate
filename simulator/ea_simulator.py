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
import hashlib
import json
import math
import re
import time
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlsplit

import httpx


def validate_local_backend_origin(raw: str) -> str:
    """Limit fake lifecycle writers to an explicit numeric loopback HTTP origin.

    This rejects remote hosts, userinfo, arbitrary paths and inherited proxy
    routing. It cannot prove that a local reverse proxy is not forwarding.
    """
    if not raw or any(ord(char) <= 32 or ord(char) == 127 for char in raw):
        raise ValueError("Simulator backend must be a local HTTP origin")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Simulator backend has an invalid host or port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or port == 0
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Synthetic execution is local-only: use http://127.0.0.1:<port> "
            "or http://[::1]:<port>, with no userinfo, path, query or fragment"
        )
    return raw.rstrip("/")


BANNER = (
    "================ SignalGate EA SIMULATOR (NOT REAL TRADING) ================\n"
    " This is a simulator. No broker connection. No trades are placed.\n"
    " It only posts fake execution/management events to the backend for testing.\n"
    "===========================================================================\n"
)


def _route_safe_command_id(value: Any) -> bool:
    """Only canonical ASCII IDs may select a synthetic command callback route.

    Backend-generated command IDs are CMD- plus uppercase hexadecimal; this
    also preserves hyphen/underscore local fixture IDs without admitting URL
    delimiters, encoding escapes, control characters or oversized paths.
    """
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None
    )


def _safe_demo_symbol(value: Any) -> bool:
    """Prevent malformed broker labels from forging synthetic receipt/log lines.

    Do not restrict ordinary ASCII broker suffix punctuation such as '.'/'#';
    reject unprintable, invisible, whitespace and oversized symbols instead.
    """
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value.isascii()
        and value.isprintable()
        and not any(char.isspace() for char in value)
    )


def _positive_finite(value: Any) -> bool:
    """Match the demo EA minimum for usable SL/TP prices (no bool/NaN/Inf)."""
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _has_valid_take_profits(command: Dict[str, Any]) -> bool:
    """Reject malformed targets before ACK or fake SUCCESS receipts.

    Backend CommandOut emits levels 1-3. A valid TP1 is required; malformed
    later levels must not be silently omitted or poison synthetic evidence.
    """
    targets = command.get("take_profits")
    if not isinstance(targets, list):
        return False
    levels = set()
    previous_level = 0
    for tp in targets:
        if not isinstance(tp, dict):
            return False
        level = tp.get("level")
        lot = tp.get("lot")
        if (
            type(level) is not int
            or level not in (1, 2, 3)
            or level in levels
            or level <= previous_level
            or not _positive_finite(tp.get("price"))
            or (lot is not None and not _positive_finite(lot))
        ):
            return False
        levels.add(level)
        previous_level = level
    return 1 in levels


def _has_boolean_split_mode(command: Dict[str, Any]) -> bool:
    """Direct in-process calls must enforce the same strict flag as polling."""
    return (
        "split_ticket_demo_partial_mode" not in command
        or type(command["split_ticket_demo_partial_mode"]) is bool
    )


def _has_complete_split_ticket_lots(command: Dict[str, Any]) -> bool:
    """Never invent sizes for synthetic split-ticket children.

    A reported child fill/closure needs an explicit finite positive stage lot.
    An absent lot cannot be substituted with the unrelated command lot size.
    """
    if command.get("split_ticket_demo_partial_mode") is not True:
        return True
    targets = command.get("take_profits")
    return (
        isinstance(targets, list)
        and bool(targets)
        and all(
            isinstance(tp, dict) and _positive_finite(tp.get("lot"))
            for tp in targets
        )
    )


def _has_valid_price_geometry(command: Dict[str, Any]) -> bool:
    """Match parser direction/stop/target ordering before synthetic ACK.

    A positive price is not enough: inverted BUY/SELL stops or targets would
    fabricate profitable-stage evidence for an impossible signal. An optional
    explicit entry also has to sit between the stop and TP1. This does not
    establish a real broker quote or execution acceptance.
    """
    prices_by_level = {
        tp["level"]: tp["price"] for tp in command["take_profits"]
    }
    targets = [prices_by_level[level] for level in sorted(prices_by_level)]
    stop = command["initial_stop_loss"]
    entry = command.get("entry_price")
    if entry is None:
        entry = _implied_entry(command)
    if command["direction"] == "BUY":
        return (
            stop < targets[0]
            and all(a < b for a, b in zip(targets, targets[1:]))
            and stop < entry < targets[0]
        )
    return (
        stop > targets[0]
        and all(a > b for a, b in zip(targets, targets[1:]))
        and stop > entry > targets[0]
    )


class HttpLike(Protocol):
    """Minimal interface satisfied by both httpx.Client and FastAPI TestClient."""

    def get(self, url: str, **kwargs) -> Any: ...
    def post(self, url: str, **kwargs) -> Any: ...


def _fake_ticket(base: int, offset: int) -> str:
    # Deterministic pseudo ticket numbers for the simulator.
    return str(base + offset)


def _synthetic_ticket_base(user_id: str, command_id: str) -> int:
    """Reserve distinct fake ticket ranges for distinct synthetic commands.

    The old fixed 100000 ticket was reused for every signal/user, potentially
    giving unrelated synthetic lifecycles the same apparent broker identity.
    A stable digest permits repeatable isolated tests; this is NOT a broker ID.
    """
    identity = json.dumps([user_id, command_id], separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    # 56 digest bits * 8 slots fits inside signed 64-bit ticket range.
    return 1_000_000 + 8 * int.from_bytes(digest[:7], "big")


class EASimulator:
    """Polls the backend and simulates the EA lifecycle for one user."""

    def __init__(
        self,
        http: HttpLike,
        user_id: str,
        api_key: str,
        license_key: str = "",
        delay: float = 0.5,
        verbose: bool = True,
        scenario: str = "win",
    ) -> None:
        # Invalid timing can fail after ACK/OPENED and leave false partial
        # synthetic history. Reject it before touching the HTTP client.
        if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
            raise ValueError("Simulator delay must be finite and non-negative")
        self.http = http
        self.user_id = user_id
        self.headers = {"X-EA-API-Key": api_key}
        if license_key:
            self.headers["X-SG-License-Key"] = license_key
        self.delay = delay
        self.verbose = verbose
        if scenario not in {"win", "stop_out"}:
            raise ValueError("scenario must be 'win' or 'stop_out'")
        self.scenario = scenario
        self.processed: set = set()  # local idempotency, like the real EA

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[SIMULATOR] {msg}")

    def _sleep(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    def _require_truthful_stop_out(self, command: Dict[str, Any]) -> None:
        """Do not report one child's stop-out as closure of multiple children."""
        if (
            self.scenario == "stop_out"
            and command.get("split_ticket_demo_partial_mode") is True
            and len(command["take_profits"]) > 1
        ):
            raise RuntimeError(
                "Synthetic split-ticket stop-out cannot prove every child closed; "
                "refusing fake execution before acknowledgement"
            )

    def _valid_command(self, command: Any) -> bool:
        """Apply the same fail-closed poll guard to direct synthetic writers.

        Tests can call simulate_lifecycle/post_execution without polling. Such
        calls must not bypass owner, demo-only, entry, or price validation and
        manufacture a valid-looking synthetic execution receipt.
        """
        if not isinstance(command, dict):
            return False
        return not (
            not _route_safe_command_id(command.get("command_id"))
            or any(
                not isinstance(command.get(key), str) or not command[key].strip()
                for key in ("command_id", "symbol", "direction")
            )
            or not _safe_demo_symbol(command.get("symbol"))
            or command.get("user_id") != self.user_id
            or command.get("demo_only") is not True
            or command.get("entry_type") != "MARKET"
            or command.get("direction") not in {"BUY", "SELL"}
            or not _has_boolean_split_mode(command)
            or not _positive_finite(command.get("initial_stop_loss"))
            or not _positive_finite(command.get("lot_size"))
            or (
                command.get("entry_price") is not None
                and not _positive_finite(command["entry_price"])
            )
            or not _has_valid_take_profits(command)
            or not _has_complete_split_ticket_lots(command)
            or not _has_valid_price_geometry(command)
        )

    # --- backend calls ----------------------------------------------------

    def poll(self) -> Optional[Dict[str, Any]]:
        resp = self.http.get(
            "/commands/pending",
            params={"user_id": self.user_id},
            headers=self.headers,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                "Synthetic command poll was not accepted; refusing fake execution"
            )
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict) or "command" not in data:
            raise RuntimeError(
                "Synthetic command poll returned an invalid receipt; refusing fake execution"
            )
        command = data["command"]
        if command is not None and not self._valid_command(command):
            raise RuntimeError(
                "Synthetic command poll returned an invalid command; refusing fake execution"
            )
        return command

    def ack_received(self, command_id: str) -> None:
        response = self.http.post(
            f"/commands/{command_id}/received", json={}, headers=self.headers
        )
        # An HTTP 200 without a confirmed command claim is not permission
        # to fabricate any downstream execution or management receipts.
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or payload.get("status") != "received"
        ):
            raise RuntimeError(
                "Synthetic command acknowledgement was not accepted; "
                "refusing to report simulated fills"
            )

    def post_execution(self, command: Dict[str, Any], child_tickets: List[str]) -> None:
        if not _has_boolean_split_mode(command):
            raise RuntimeError(
                "Synthetic split-ticket mode must be boolean; refusing fake execution"
            )
        if not _has_complete_split_ticket_lots(command):
            raise RuntimeError(
                "Synthetic split-ticket stages lack positive explicit lots; "
                "refusing fake execution"
            )
        if not self._valid_command(command):
            raise RuntimeError(
                "Synthetic command failed direct-call preflight; refusing fake execution"
            )
        # Simulate a small favourable entry near the implied entry.
        entry = command.get("entry_price")
        executed_price = entry if entry is not None else _implied_entry(command)
        # A non-split demo has one position of the approved command size.
        # TP stage lots represent separate fake child fills only in split mode.
        reported_lots = command["lot_size"]
        if command.get("split_ticket_demo_partial_mode") is True:
            reported_lots = (
                sum(tp.get("lot") or 0 for tp in command["take_profits"])
                or reported_lots
            )
        payload = {
            "status": "SUCCESS",
            "broker_ticket": child_tickets[0] if child_tickets else None,
            "child_tickets_json": json.dumps(child_tickets),
            "executed_symbol": command["symbol"],
            "executed_direction": command["direction"],
            "requested_price": entry,
            "executed_price": executed_price,
            "lot_size": reported_lots,
            "initial_stop_loss": command["initial_stop_loss"],
            "tp1": _tp_price(command, 1),
            "tp2": _tp_price(command, 2),
            "tp3": _tp_price(command, 3),
            "spread_at_execution": 20,
            "slippage": 0,
        }
        response = self.http.post(
            f"/commands/{command['command_id']}/execution",
            json=payload,
            headers=self.headers,
        )
        try:
            receipt = response.json()
        except ValueError:
            receipt = None
        if (
            response.status_code != 200
            or not isinstance(receipt, dict)
            or receipt.get("status") != "ok"
        ):
            raise RuntimeError(
                "Synthetic execution report was not accepted; "
                "refusing to emit management events"
            )

    def post_event(self, command_id: str, **fields) -> None:
        response = self.http.post(
            f"/commands/{command_id}/management_event",
            json=fields,
            headers=self.headers,
        )
        try:
            receipt = response.json()
        except ValueError:
            receipt = None
        if (
            response.status_code != 200
            or not isinstance(receipt, dict)
            or receipt.get("status") != "ok"
        ):
            raise RuntimeError(
                "Synthetic management event was not accepted; "
                "halting synthetic lifecycle"
            )

    # --- lifecycle --------------------------------------------------------

    def simulate_lifecycle(self, command: Dict[str, Any]) -> None:
        """Simulate open -> TP1 -> BE -> TP2 -> SL@TP1 -> TP3 -> fully closed."""
        if not _has_boolean_split_mode(command):
            raise RuntimeError(
                "Synthetic split-ticket mode must be boolean; refusing fake execution"
            )
        if not _has_complete_split_ticket_lots(command):
            raise RuntimeError(
                "Synthetic split-ticket stages lack positive explicit lots; "
                "refusing fake execution before acknowledgement"
            )
        if not self._valid_command(command):
            raise RuntimeError(
                "Synthetic command failed direct-call preflight; refusing fake execution"
            )
        self._require_truthful_stop_out(command)
        cid = command["command_id"]
        base_ticket = _synthetic_ticket_base(self.user_id, cid)

        # Open child tickets (split-ticket demo mode) or single ticket.
        if command.get("split_ticket_demo_partial_mode"):
            child_tickets = [_fake_ticket(base_ticket, i) for i in range(len(command["take_profits"]))]
        else:
            child_tickets = [_fake_ticket(base_ticket, 0)]

        if self.scenario == "stop_out":
            self._simulate_stop_out(command, child_tickets)
            return

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
        # A lone TP1 closes the only synthetic child: there is no remaining
        # position on which a broker could modify the stop.
        if len(command["take_profits"]) > 1:
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
            # A two-target command is fully closed at TP2; modifying a stop
            # after the final child closes would fabricate broker evidence.
            if _tp_price(command, 3) is not None:
                self.post_event(cid, event_type="SL_MOVE_TP1_SUCCESS", stage="TP2_DONE",
                                requested_action="MOVE_SL_TP1", result="SUCCESS",
                                stop_loss_before=entry, stop_loss_after=_tp_price(command, 1))
            self._sleep()

        if _tp_price(command, 3) is not None:
            # TP3
            self.log("Simulating TP3 reached + final close")
            # TP1 + TP3 is valid parser input: do not invent a TP2_DONE
            # management milestone if no TP2 stage was ever recorded.
            preceding_stage = (
                "TP2_DONE" if _tp_price(command, 2) is not None else "TP1_DONE"
            )
            self.post_event(cid, event_type="TP3_REACHED", stage=preceding_stage,
                            result="SUCCESS", price=_tp_price(command, 3))
            self.post_event(cid, broker_ticket=child_tickets[-1],
                            event_type="TP3_CLOSE_SUCCESS", stage="TP3_DONE",
                            result="SUCCESS", price=_tp_price(command, 3))
            self._sleep()

        # Fully closed
        self.log("Simulating FULLY_CLOSED")
        self.post_event(cid, event_type="FULLY_CLOSED", stage="FULLY_CLOSED",
                        result="SUCCESS")

    def _simulate_stop_out(
        self, command: Dict[str, Any], child_tickets: List[str]
    ) -> None:
        """Exercise the losing path without placing any broker trade."""
        cid = command["command_id"]
        sl = command["initial_stop_loss"]
        self.log(f"Simulating OPEN then STOP-OUT for {cid}")
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
        self.post_event(
            cid,
            broker_ticket=child_tickets[0],
            event_type="STOP_LOSS_HIT",
            stage="FULLY_CLOSED",
            result="SUCCESS",
            price=sl,
            stop_loss_after=sl,
        )
        self.post_event(
            cid,
            event_type="FULLY_CLOSED",
            stage="FULLY_CLOSED",
            result="SUCCESS",
        )

    def run_once(self, expected_command_id: Optional[str] = None) -> bool:
        """Poll once and only simulate the caller's expected command if supplied.

        Returns True if a command was processed.
        """
        command = self.poll()
        if command is None:
            return False
        cid = command["command_id"]
        # The scripted demo has just approved one command, but the backend
        # intentionally polls the oldest pending command for this user. Never
        # manufacture execution receipts for an unrelated older approval.
        # Poll itself claims a pending command; do not silently retry or fake
        # a successful receipt after a mismatch.
        if expected_command_id is not None and cid != expected_command_id:
            raise RuntimeError(
                "Pending demo command differs from newly approved command; "
                "refusing synthetic execution"
            )
        if cid in self.processed:
            self.log(f"DUPLICATE_COMMAND {cid} ignored (local idempotency).")
            return False
        # Fail before ACK: the stop-out emulator currently reports a hit for
        # one child only, so it cannot truthfully close a split multi-child set.
        self._require_truthful_stop_out(command)
        self.log(f"Received command {cid} ({command['symbol']} {command['direction']})")
        self.ack_received(cid)
        self.processed.add(cid)
        self.simulate_lifecycle(command)
        self.log(f"Command {cid} lifecycle complete (FULLY_CLOSED).")
        return True

    def run_forever(self, poll_interval: float = 2.0) -> None:
        if (
            type(poll_interval) not in (int, float)
            or not math.isfinite(poll_interval)
            or poll_interval <= 0
        ):
            raise ValueError("Simulator poll interval must be finite and positive")
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
    # Preserve narrow valid price brackets instead of rounding to 5 digits.
    # The poll guard rejects the case where float precision leaves no point
    # strictly between the stop and TP1.
    return sl + (tp1 - sl) * 0.2


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalGate EA SIMULATOR (no trading)")
    parser.add_argument("--user-id", required=True, help="e.g. USER-000001")
    parser.add_argument("--api-key", default="local-demo-ea-key")
    parser.add_argument("--license-key", default="")
    parser.add_argument(
        "--scenario",
        choices=["win", "stop_out"],
        default="win",
        help="Simulator lifecycle: full targets or explicit stop-out loss",
    )
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
    try:
        backend = validate_local_backend_origin(args.backend)
    except ValueError as exc:
        parser.error(str(exc))
    # Check timing before opening a client or acknowledging a fake command.
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error("Simulator --delay must be finite and non-negative")
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        parser.error("Simulator --poll-interval must be finite and positive")

    print(BANNER)
    # No ambient HTTP(S)_PROXY/redirect may receive the EA key or fake fills.
    with httpx.Client(
        base_url=backend, timeout=10.0, follow_redirects=False, trust_env=False
    ) as http:
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
            parser.error(
                "Simulator refused: /health did not confirm an active "
                "local demo-only backend"
            )
        sim = EASimulator(
            http=http,
            user_id=args.user_id,
            api_key=args.api_key,
            license_key=args.license_key,
            delay=args.delay,
            scenario=args.scenario,
        )
        if args.once:
            if not sim.run_once():
                sim.log("No pending command found.")
        else:
            sim.run_forever(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
