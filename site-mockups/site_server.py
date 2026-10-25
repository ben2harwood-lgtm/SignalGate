"""Loopback-only server for historical SignalGate site design previews.

This is not a lead-intake service. The legacy request POST route is disabled
and never reads, forwards or persists submitted personal data.
"""
from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8088
STATIC_ROOT = Path(__file__).resolve().parent


class SiteHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        # Serving the caller's CWD could expose repository files or local .env.
        # The preview must only serve its own non-secret static mockup folder.
        kwargs["directory"] = str(STATIC_ROOT)
        super().__init__(*args, **kwargs)

    def do_POST(self) -> None:
        if self.path != "/api/demo-requests":
            self.send_error(404, "Not found")
            return

        # This July design mockup is not an authorised personal-data collector.
        # Close without parsing even a well-formed request body.
        self.close_connection = True
        self._send_json(
            {"ok": False, "error": "Design preview only; request intake disabled."},
            status=410,
        )

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), SiteHandler)
    print(f"SignalGate historical site preview: http://{HOST}:{PORT}/site-2-editorial-transparency.html")
    print("Demo request intake DISABLED; no contact details are stored.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SignalGate site preview.")
    finally:
        server.server_close()
