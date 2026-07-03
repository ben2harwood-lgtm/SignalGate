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
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
}

# Lead submissions are written OUTSIDE the served directory (defence in depth on
# top of the GET allowlist) so they can never be downloaded via the site.
REQUEST_LOG = SITE_DIR.parent / "site-requests" / "demo-requests.jsonl"

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

    # --- POST: capture a demo request -------------------------------------
    def do_POST(self) -> None:
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


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), SiteHandler)
    print(f"SignalGate demo site running at http://{HOST}:{PORT}/{DEFAULT_PAGE}")
    print(f"Demo requests will be written to {REQUEST_LOG}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SignalGate demo site.")
