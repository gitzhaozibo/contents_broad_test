"""E2E fixtures: serve the static portal so Playwright can drive the UI.

A lightweight stdlib HTTP server hosts ``index.html`` under ``/app01/`` and
provides stubbed ``/app01/api/*`` JSON responses, so the front-end logic
(tabs, admin file table, search, delete) is tested without Azure or FastAPI.
The bound URL is exposed as the Playwright ``base_url`` and reflects the active
TEST_ENV (e2e tests are skipped automatically when no browser is installed).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_HTML = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
HEALTH_HTML = (REPO_ROOT / "health_check.html").read_text(encoding="utf-8")

FILES = [
    {"name": "manuals/guide.pdf", "size": 1024, "last_modified": "2024-01-01T00:00:00+00:00"},
    {"name": "manuals/setup.pdf", "size": 2048, "last_modified": "2024-02-01T00:00:00+00:00"},
]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        if self.path.startswith("/app01/api/me"):
            self._json({"name": "tester@example.com", "is_admin": True})
        elif self.path.startswith("/app01/api/health"):
            self._json({"status": "ok", "blob": "ok"})
        elif self.path.startswith("/app01/api/admin/files"):
            self._json({"files": FILES})
        elif self.path.startswith("/app01/health_check"):
            self._html(HEALTH_HTML)
        else:
            self._html(INDEX_HTML)

    def do_POST(self):
        self._json({"deleted": "ok"})


@pytest.fixture(scope="session")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="session")
def base_url(server):
    return server
