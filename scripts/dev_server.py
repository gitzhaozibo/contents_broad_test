"""Local dev server: emulates nginx for manual testing (no Azure, no Easy Auth).

Serves the portal UI under /app01/, mirrors /app01/content/ from CONTENT_ROOT,
and proxies /app01/api/* to the FastAPI backend on 127.0.0.1:8000 while
injecting an admin X-MS-CLIENT-PRINCIPAL header so admin features are testable.

Usage:
    python scripts/dev_server.py            # listens on http://127.0.0.1:8080
    DEV_ADMIN=0 python scripts/dev_server.py  # without admin role
"""

import base64
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://127.0.0.1:8000"
CONTENT_ROOT = Path(os.environ.get("CONTENT_ROOT") or ROOT / "portal-content")
PORT = int(os.environ.get("DEV_PORT", "8080"))

if os.environ.get("DEV_ADMIN", "1") != "0":
    _claims = [
        {"typ": "roles", "val": "FileAdmin"},
        {"typ": "name", "val": "dev-admin@example.com"},
    ]
else:
    _claims = [{"typ": "name", "val": "dev-user@example.com"}]
PRINCIPAL = base64.b64encode(json.dumps({"claims": _claims}).encode()).decode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else None
        url = API_BASE + self.path[len("/app01") :]
        req = urllib.request.Request(url, data=data, method=self.command)
        req.add_header("X-MS-CLIENT-PRINCIPAL", PRINCIPAL)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            with urllib.request.urlopen(req) as resp:
                self._send(resp.status, resp.read(), resp.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as exc:
            self._send(exc.code, exc.read(), "application/json")
        except OSError:
            self._send(502, b'{"detail":"API server unreachable"}', "application/json")

    def _static(self):
        if self.path.startswith("/app01/content/"):
            rel = self.path[len("/app01/content/") :]
            target = (CONTENT_ROOT / rel).resolve()
            if target.is_file() and CONTENT_ROOT.resolve() in target.parents:
                self._send(200, target.read_bytes(), "application/octet-stream")
            else:
                self._send(404, b"not found", "text/plain")
        elif self.path.startswith("/app01/health_check"):
            body = (ROOT / "health_check.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
        else:
            body = (ROOT / "index.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/app01/api/"):
            self._proxy()
        else:
            self._static()

    def do_POST(self):
        if self.path.startswith("/app01/api/"):
            self._proxy()
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):
        print("[dev]", fmt % args)


if __name__ == "__main__":
    print(f"Portal UI:    http://127.0.0.1:{PORT}/app01/")
    print(f"Health page:  http://127.0.0.1:{PORT}/app01/health_check")
    print(f"Admin header: {'ON' if len(_claims) > 1 else 'OFF'}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
