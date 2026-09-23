"""Local reverse proxy matching deploy/nginx.conf path routing.

Used by ``python app.py`` so the laptop suite exposes one public origin
(same UX as Docker Compose + nginx), while the three Flask apps listen on
loopback only.
"""

from __future__ import annotations

import http.client
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def pick_upstream(
    path: str,
    *,
    nxc: tuple[str, int],
    pn: tuple[str, int],
    np: tuple[str, int],
) -> tuple[str, int]:
    """Mirror deploy/nginx.conf location precedence."""
    if path.startswith("/portals/marketing"):
        return np
    if path.startswith("/portals"):
        return nxc
    if path.startswith("/login"):
        return nxc
    if path == "/admin":
        return nxc
    if path.startswith("/platform_admin/"):
        return nxc
    if path.startswith("/api/platform-admin"):
        return nxc
    if path == "/api/login":
        return nxc
    return pn


def wait_for_upstream(host: str, port: int, *, timeout_sec: float = 60.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/health/live")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if 200 <= resp.status < 500:
                return True
        except OSError:
            pass
        time.sleep(0.35)
    return False


def choose_listen_port(preferred: int, host: str = "0.0.0.0") -> int:
    """Bind preferred port; if :80 is denied (common on Windows), try 8080."""
    candidates = [preferred]
    if preferred == 80 and 8080 not in candidates:
        candidates.append(8080)
    last_err: OSError | None = None
    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host if host != "0.0.0.0" else "", port))
            return port
        except OSError as exc:
            last_err = exc
        finally:
            sock.close()
    raise OSError(f"Could not bind proxy port (tried {candidates}): {last_err}")


def make_handler(
    *,
    nxc: tuple[str, int],
    pn: tuple[str, int],
    np: tuple[str, int],
) -> type[BaseHTTPRequestHandler]:
    class _ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            if args and str(args[0]).startswith(("4", "5")):
                super().log_message(fmt, *args)

        def _proxy(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path or "/"
            upstream_host, upstream_port = pick_upstream(path, nxc=nxc, pn=pn, np=np)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""

            headers: dict[str, str] = {}
            for key, value in self.headers.items():
                if key.lower() in _HOP_BY_HOP:
                    continue
                headers[key] = value

            public_host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
            headers["Host"] = public_host
            headers["X-Real-IP"] = self.client_address[0]
            headers["X-Forwarded-For"] = self.client_address[0]
            headers["X-Forwarded-Proto"] = "http"
            headers["X-Forwarded-Host"] = public_host

            try:
                conn = http.client.HTTPConnection(upstream_host, upstream_port, timeout=600)
                conn.request(self.command, self.path, body=body or None, headers=headers)
                resp = conn.getresponse()
                payload = resp.read()
            except OSError as exc:
                self.send_error(502, f"Upstream {upstream_host}:{upstream_port} unavailable: {exc}")
                return

            self.send_response(resp.status, resp.reason)
            for key, value in resp.getheaders():
                if key.lower() in _HOP_BY_HOP:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD" and payload:
                self.wfile.write(payload)
            conn.close()

        def do_GET(self) -> None:
            self._proxy()

        def do_POST(self) -> None:
            self._proxy()

        def do_PUT(self) -> None:
            self._proxy()

        def do_PATCH(self) -> None:
            self._proxy()

        def do_DELETE(self) -> None:
            self._proxy()

        def do_OPTIONS(self) -> None:
            self._proxy()

        def do_HEAD(self) -> None:
            self._proxy()

    return _ProxyHandler


def start_proxy(
    *,
    listen_host: str,
    listen_port: int,
    nxc: tuple[str, int],
    pn: tuple[str, int],
    np: tuple[str, int],
) -> ThreadingHTTPServer:
    handler = make_handler(nxc=nxc, pn=pn, np=np)
    server = ThreadingHTTPServer((listen_host, listen_port), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="nexus-local-proxy", daemon=True)
    thread.start()
    return server
