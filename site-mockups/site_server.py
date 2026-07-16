"""Local preview server for the SignalGate demo site.

Serves ONLY the chosen public site page(s) and accepts demo requests at
POST /api/demo-requests. Submissions are written to a log OUTSIDE the served
web root so prospect PII can never be fetched back over HTTP, and every other
file in this directory (internal strategy docs, drafts, this source file) is
404'd rather than served.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8088

SITE_DIR = Path(__file__).parent
DEFAULT_PAGE = "site-2-editorial-transparency.html"

# Only these public pages are served. Everything else in the directory
# (MESSAGE_MAP.md, _copy-deck.md, direction-*.html drafts, this server's source)
# is deliberately NOT public.
ALLOWED_PAGES = {
    "site-1-quant-desk.html",
    "site-2-editorial-transparency.html",
    "site-3-verified-accountable.html",
    "launch.html",
}

# Lead submissions are written OUTSIDE the served directory (defence in depth on
# top of the GET allowlist) so they can never be downloaded via the site.
REQUEST_LOG = SITE_DIR.parent / "site-requests" / "demo-requests.jsonl"
WAITLIST_LOG = SITE_DIR.parent / "site-requests" / "waitlist.jsonl"

WAITLIST_ALLOWED_FIELDS = {"email", "name", "telegram", "ref"}
FOUNDING_CAP = 100  # first N are "founding members" — a real, capped cohort

MAX_BODY_BYTES = 32_000
MAX_FIELD_LEN = 500
ALLOWED_FIELDS = {
    "reference", "name", "email", "plan", "platform", "signalSource",
    "channel", "notes", "consent",
}
REQUIRED_FIELDS = ["reference", "name", "email", "plan", "platform", "signalSource"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SiteHandler(SimpleHTTPRequestHandler):
    # --- GET: serve only allowlisted public pages -------------------------
    def do_GET(self) -> None:
        name = self.path.split("?", 1)[0].lstrip("/")
        # Real waitlist size for the launch page. Only ever the true count —
        # the page hides it below a threshold rather than inflating it.
        if name == "api/waitlist/count":
            self._send_json({"count": _waitlist_count(), "foundingCap": FOUNDING_CAP})
            return
        # A member's live status (position in line, referral count) by ref code.
        if name == "api/waitlist/status":
            qs = parse_qs(urlparse(self.path).query)
            code = (qs.get("code", [""])[0] or "").strip()
            status = _member_status(code)
            if status is None:
                self.send_error(404, "Not found")
                return
            self._send_json(status)
            return
        if name in ("", "index.html"):
            name = DEFAULT_PAGE
        if name not in ALLOWED_PAGES:
            self.send_error(404, "Not found")
            return
        self.path = "/" + name
        super().do_GET()

    def do_HEAD(self) -> None:  # keep HEAD consistent with GET
        name = self.path.split("?", 1)[0].lstrip("/")
        if name in ("", "index.html"):
            name = DEFAULT_PAGE
        if name not in ALLOWED_PAGES:
            self.send_error(404, "Not found")
            return
        self.path = "/" + name
        super().do_HEAD()

    # --- POST: capture a demo request or waitlist signup -------------------
    def do_POST(self) -> None:
        if self.path == "/api/waitlist":
            self._handle_waitlist()
            return
        if self.path != "/api/demo-requests":
            self.send_error(404, "Not found")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Bad content length")
            return

        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_error(400, "Bad request size")
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        if not isinstance(payload, dict):
            self.send_error(400, "Invalid payload")
            return

        # Drop unknown keys and cap lengths so junk / injected fields are never
        # stored, then validate the required fields and email shape.
        clean: dict[str, Any] = {}
        for key in ALLOWED_FIELDS:
            if key in payload and payload[key] is not None:
                clean[key] = str(payload[key])[:MAX_FIELD_LEN]

        missing = [k for k in REQUIRED_FIELDS if not clean.get(k, "").strip()]
        if missing:
            self.send_error(422, "Missing required fields")
            return
        if not _EMAIL_RE.match(clean["email"]):
            self.send_error(422, "Invalid email")
            return

        clean["receivedAt"] = datetime.now(timezone.utc).isoformat()
        REQUEST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with REQUEST_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=True) + "\n")

        self._send_json({"ok": True, "reference": clean["reference"]})

    # --- waitlist ----------------------------------------------------------
    def _handle_waitlist(self) -> None:
        """Store a waitlist signup OUTSIDE the web root, deduped by email.

        Same hardening as demo requests: size cap, JSON only, unknown keys
        dropped, field lengths capped, email shape validated. A duplicate
        email is acknowledged (alreadyJoined) rather than stored twice, so
        the public count can never be inflated by resubmits.
        """
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Bad content length")
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_error(400, "Bad request size")
            return
        raw_body = self.rfile.read(content_length)
        try:
            payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        if not isinstance(payload, dict):
            self.send_error(400, "Invalid payload")
            return

        clean: dict[str, Any] = {}
        for key in WAITLIST_ALLOWED_FIELDS:
            if key in payload and payload[key] is not None:
                clean[key] = str(payload[key])[:MAX_FIELD_LEN]

        email = clean.get("email", "").strip().lower()
        if not email or not _EMAIL_RE.match(email):
            self.send_error(422, "Invalid email")
            return
        clean["email"] = email

        rows = _iter_waitlist_rows()

        # Idempotent by email: a repeat signup returns the SAME status (so a
        # resubmit can't inflate the count or mint a second referral code).
        existing = next((r for r in rows if r.get("email", "").lower() == email), None)
        if existing:
            self._send_json({"ok": True, "alreadyJoined": True,
                             **_member_status(existing["refCode"])})
            return

        # A referral only counts if the ref code resolves to a real member.
        ref = (clean.pop("ref", "") or "").strip()
        referred_by = ref if any(r.get("refCode") == ref for r in rows) else ""
        clean["referredBy"] = referred_by

        # Unique short referral code for the new member.
        existing_codes = {r.get("refCode") for r in rows}
        code = secrets.token_hex(4)
        while code in existing_codes:
            code = secrets.token_hex(4)
        clean["refCode"] = code
        clean["joinedAt"] = datetime.now(timezone.utc).isoformat()

        WAITLIST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WAITLIST_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=True) + "\n")

        self._send_json({"ok": True, "alreadyJoined": False, **_member_status(code)})

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _iter_waitlist_rows() -> list[dict[str, Any]]:
    if not WAITLIST_LOG.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in WAITLIST_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _waitlist_count() -> int:
    return len(_iter_waitlist_rows())


def _waitlist_has_email(email: str) -> bool:
    return any(r.get("email", "").lower() == email for r in _iter_waitlist_rows())


def _referral_count(rows: list[dict[str, Any]], code: str) -> int:
    return sum(1 for r in rows if r.get("referredBy") == code)


def _member_status(code: str) -> dict[str, Any] | None:
    """A member's live standing, keyed by their referral code.

    Position is the member's RANK when everyone is ordered by referral count
    (desc) then join time (asc) — so referring a friend genuinely moves you up
    the queue, past people who joined earlier but referred no-one. This is the
    honest Robinhood-style loop: real numbers, no invented positions.
    """
    if not code:
        return None
    rows = _iter_waitlist_rows()
    me = next((r for r in rows if r.get("refCode") == code), None)
    if me is None:
        return None
    counts = {r["refCode"]: _referral_count(rows, r["refCode"]) for r in rows if r.get("refCode")}
    ordered = sorted(
        rows,
        key=lambda r: (-counts.get(r.get("refCode", ""), 0), r.get("joinedAt", "")),
    )
    position = next(i for i, r in enumerate(ordered, start=1) if r.get("refCode") == code)
    referrals = counts.get(code, 0)
    return {
        "refCode": code,
        "position": position,
        "total": len(rows),
        "referrals": referrals,
        "founding": position <= FOUNDING_CAP,
        "foundingCap": FOUNDING_CAP,
    }


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), SiteHandler)
    print(f"SignalGate demo site running at http://{HOST}:{PORT}/{DEFAULT_PAGE}")
    print(f"Launch/waitlist page at http://{HOST}:{PORT}/launch.html")
    print(f"Demo requests will be written to {REQUEST_LOG}")
    print(f"Waitlist signups will be written to {WAITLIST_LOG}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SignalGate demo site.")
