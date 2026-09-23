"""Local suite launcher — ONE process, ONE public port (Docker path routing).

Usage::

    python app.py

Mounts NexusCore + PrimeNet + NexPulse in a single WSGI process and listens only
on ``PROXY_HTTP_PORT`` (default 80, falls back to 8080 if privileged bind fails).
Path routing matches ``deploy/nginx.conf``. Open::

    http://localhost:<port>/portals

There are no listeners on 8000 / 8001 / 8002 when launched this way.

WSGI import (``gunicorn app:app``) still exposes PrimeNet only, for Docker
compatibility. Prefer ``primenet_app:app`` / ``nexuscore_app:app`` /
``nexpulse_app:app`` in compose.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Gunicorn / Docker: keep a WSGI callable pointing at PrimeNet.
from primenet_app import app  # noqa: E402,F401


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _prepare_suite_env(public_port: int) -> None:
    """Same-origin env — identical idea to Docker compose + nginx."""
    os.environ.setdefault("NCM_DISABLE_AUTO_BROWSER", "1")
    os.environ.setdefault("NCM_SHARED_ACTIVATION", "1")
    os.environ["NEXUS_PUBLIC_URL_FROM_REQUEST"] = "1"
    os.environ["NEXUS_PUBLIC_URL"] = ""
    os.environ["NEXUSCORE_PUBLIC_URL"] = ""
    os.environ["PRIMENET_PUBLIC_URL"] = ""
    os.environ["NEXPULSE_PUBLIC_URL"] = ""
    os.environ["NEXUS_COOKIE_DOMAIN"] = ""
    # NexPulse → PrimeNet over the same single port (in-process path routing).
    os.environ["NEXUS_PRIMENET_API_URL"] = f"http://127.0.0.1:{public_port}"
    os.environ.setdefault("NEXUS_PORTAL_API_TOKEN", "local-dev-portal-token")


def _open_browser(url: str) -> None:
    if os.name != "nt":
        return
    if _env_true("NCM_CONTAINER") or _env_true("NCM_DISABLE_AUTO_BROWSER"):
        return
    try:
        subprocess.run(["powershell", "-Command", f"Start-Process '{url}'"], check=False)
    except Exception as exc:
        print(f"[WARNING] Could not open browser: {exc}")


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except ImportError:
        pass

    from core.platform.base_app import ConciseRequestHandler
    from core.platform.local_proxy import choose_listen_port, make_suite_wsgi
    from werkzeug.serving import make_server

    preferred = int(os.getenv("PROXY_HTTP_PORT", "80"))
    listen_host = os.getenv("PROXY_LISTEN_HOST", "0.0.0.0")

    try:
        port = choose_listen_port(preferred, host=listen_host)
    except OSError as exc:
        print(f"[ERROR] Could not bind suite port: {exc}", file=sys.stderr)
        return 1
    if port != preferred:
        print(f"[INFO] Port {preferred} unavailable — listening on {port}")

    _prepare_suite_env(port)

    # Import after env so NexPulse sees NEXUS_PRIMENET_API_URL for this port.
    import nexuscore_app  # noqa: WPS433
    import nexpulse_app  # noqa: WPS433

    suite = make_suite_wsgi(
        nxc=nexuscore_app.app,
        pn=app,
        np=nexpulse_app.app,
    )

    public = f"http://localhost:{port}" if port != 80 else "http://localhost"
    print("=" * 60)
    print("NexusCore suite — single port (same routing as Docker)")
    print("=" * 60)
    print(f"  Public entry   {public}/portals")
    print(f"  Engineering    {public}/dashboard")
    print(f"  Marketing      {public}/portals/marketing/")
    print(f"  Platform admin {public}/admin")
    print(f"  Activation     {public}/activation")
    print(f"  Listen         {listen_host}:{port}  (only port)")
    if _env_true("NCM_SKIP_ACTIVATION"):
        print("  [INFO] NCM_SKIP_ACTIVATION=1 — gate bypassed")
    print("Ctrl+C to stop.")
    print("=" * 60)

    server = make_server(
        listen_host,
        port,
        suite,
        threaded=True,
        request_handler=ConciseRequestHandler,
    )
    thread = threading.Thread(target=server.serve_forever, name="nexus-suite", daemon=True)
    thread.start()
    print(f"[OK] Suite listening on {public}/")
    _open_browser(f"{public}/portals")

    def _on_signal(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        thread.join()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down suite…")
        server.shutdown()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
