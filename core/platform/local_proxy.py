"""Local single-origin suite helpers (same path rules as deploy/nginx.conf).

``python app.py`` mounts NexusCore / PrimeNet / NexPulse in ONE process on ONE
port — no :8000/:8001/:8002 listeners.
"""

from __future__ import annotations

import socket
from typing import Callable

# WSGI application type
WsgiApp = Callable[..., object]


def pick_app(
    path: str,
    *,
    nxc: WsgiApp,
    pn: WsgiApp,
    np: WsgiApp,
) -> WsgiApp:
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


def make_suite_wsgi(*, nxc: WsgiApp, pn: WsgiApp, np: WsgiApp) -> WsgiApp:
    """One WSGI app that path-routes to the three Flask apps (no prefix strip)."""

    def application(environ, start_response):
        path = environ.get("PATH_INFO") or "/"
        target = pick_app(path, nxc=nxc, pn=pn, np=np)
        return target(environ, start_response)

    return application


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
    raise OSError(f"Could not bind suite port (tried {candidates}): {last_err}")


# Back-compat aliases (older suite used HTTP proxy + loopback backends)
def pick_upstream(path: str, *, nxc, pn, np):
    """Deprecated: used by unit checks — maps path to (host, port) tuples."""
    return pick_app(path, nxc=nxc, pn=pn, np=np)
