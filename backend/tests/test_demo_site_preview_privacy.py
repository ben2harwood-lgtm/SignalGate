"""Isolated privacy regression for the historical SignalGate demo-site preview.

Uses only synthetic contact details and an ephemeral loopback HTTP server.
No broker, Telegram, customer information, external service or deployment.
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import runpy
import threading
from http.server import ThreadingHTTPServer
import unittest


ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site-mockups"
SERVER_SOURCE = SITE / "site_server.py"
HTML = SITE / "site-2-editorial-transparency.html"


class PreviewPrivacyTests(unittest.TestCase):
    def test_legacy_request_post_fails_closed_and_never_persists(self) -> None:
        module = runpy.run_path(str(SERVER_SOURCE), run_name="preview_test_module")
        handler_class = module["SiteHandler"]
        log_path = SITE / "demo-requests.jsonl"
        previous = log_path.read_bytes() if log_path.exists() else None
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                payload = json.dumps({
                    "reference": "SYNTHETIC-ONLY",
                    "name": "Fictional Person",
                    "email": "person@example.invalid",
                })
                conn.request("POST", "/api/demo-requests", payload,
                             {"Content-Type": "application/json"})
                response = conn.getresponse()
                data = json.loads(response.read())
                self.assertEqual(response.status, 410)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
                self.assertIs(data["ok"], False)
                self.assertIn("disabled", data["error"])
            finally:
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        after = log_path.read_bytes() if log_path.exists() else None
        self.assertEqual(after, previous, "Legacy request body must never reach disk")

    def test_legacy_html_does_not_submit_or_retain_personal_details(self) -> None:
        page = HTML.read_text(encoding="utf-8")
        self.assertNotIn("localStorage.setItem", page)
        self.assertNotIn("localStorage.getItem", page)
        self.assertNotIn('fetch("/api/demo-requests"', page)
        self.assertNotIn("storedRequests()", page)
        self.assertIn('localStorage.removeItem("signalgate_demo_requests")', page)
        self.assertIn("not submitted or saved", page)
        self.assertIn("fictional details", page.lower())


if __name__ == "__main__":
    unittest.main()
