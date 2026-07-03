"""Local preview server for the SignalGate demo site.

Serves the static mockup files and accepts demo requests at
POST /api/demo-requests, writing them to demo-requests.jsonl.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
PORT = 8088
REQUEST_LOG = Path(__file__).with_name("demo-requests.jsonl")
MAX_BODY_BYTES = 32_000


class SiteHandler(SimpleHTTPRequestHandler):
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

        required = ["reference", "name", "email", "plan", "platform", "signalSource"]
        missing = [key for key in required if not str(payload.get(key, "")).strip()]
        if missing:
            self.send_error(422, "Missing required fields")
            return

        payload["receivedAt"] = datetime.now(timezone.utc).isoformat()
        with REQUEST_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

        self._send_json({"ok": True, "reference": payload["reference"]})

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
    print(f"SignalGate demo site running at http://{HOST}:{PORT}/site-2-editorial-transparency.html")
    print(f"Demo requests will be written to {REQUEST_LOG}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SignalGate demo site.")
