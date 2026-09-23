"""Local suite launcher — same single-origin UX as Docker + nginx.

Usage::

    python app.py

Starts NexusCore / PrimeNet / NexPulse on loopback (8000 / 8001 / 8002) and a
path-routing reverse proxy on ``PROXY_HTTP_PORT`` (default 80, falls back to
8080 on Windows if privileged bind fails). Open::

    http://localhost:<proxy>/portals

Routing matches ``deploy/nginx.conf`` (Docker). Activation unlock remains on
PrimeNet ``/activation`` via the proxy (``/activation`` → PrimeNet).

WSGI import (``gunicorn app:app``) still exposes PrimeNet only, for Docker
compatibility. Prefer ``primenet_app:app`` / ``nexuscore_app:app`` /
``nexpulse_app:app`` in compose.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Gunicorn / Docker: keep a WSGI callable pointing at PrimeNet.
from primenet_app import app  # noqa: E402,F401


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _child_env(**overrides: str) -> dict[str, str]:
    """Env for suite children — Docker-proxy style (same-origin via local proxy)."""
    env = os.environ.copy()
    env.setdefault("NCM_DISABLE_LIVE_LOGGER_TERMINAL", "1")
    env.setdefault("NCM_DISABLE_AUTO_BROWSER", "1")
    env.setdefault("NCM_SHARED_ACTIVATION", "1")
    # Match Docker: relative portal redirects + Host from the public proxy.
    env["NEXUS_PUBLIC_URL_FROM_REQUEST"] = "1"
    env["NEXUS_PUBLIC_URL"] = ""
    env["NEXUSCORE_PUBLIC_URL"] = ""
    env["PRIMENET_PUBLIC_URL"] = ""
    env["NEXPULSE_PUBLIC_URL"] = ""
    env["NEXUS_COOKIE_DOMAIN"] = ""
    # Loopback only — public entry is the proxy.
    env["FLASK_HOST"] = "127.0.0.1"
    env["NEXUS_PRIMENET_API_URL"] = "http://127.0.0.1:8001"
    env.setdefault("NEXUS_PORTAL_API_TOKEN", "local-dev-portal-token")
    env.update(overrides)
    return env


def _spawn(label: str, script: str, port: str, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    env = _child_env(FLASK_PORT=port, **(extra_env or {}))
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / script)],
        cwd=str(ROOT),
        env=env,
        creationflags=creationflags,
    )
    print(f"[OK] {label} pid={proc.pid}  (loopback :{port})")
    return proc


def _terminate(procs: list[tuple[str, subprocess.Popen]]) -> None:
    for label, proc in procs:
        if proc.poll() is not None:
            continue
        print(f"[..] Stopping {label} (pid={proc.pid})")
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
    deadline = time.time() + 8
    for label, proc in procs:
        remaining = max(0.1, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            print(f"[WARN] Force-killing {label}")
            proc.kill()


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

    from core.platform.local_proxy import (
        choose_listen_port,
        start_proxy,
        wait_for_upstream,
    )

    nxc_port = int(os.getenv("NEXUSCORE_PORT", "8000"))
    pn_port = int(os.getenv("PRIMENET_PORT", "8001"))
    np_port = int(os.getenv("NEXPULSE_PORT", "8002"))
    preferred_proxy = int(os.getenv("PROXY_HTTP_PORT", "80"))
    proxy_host = os.getenv("PROXY_LISTEN_HOST", "0.0.0.0")

    try:
        proxy_port = choose_listen_port(preferred_proxy, host=proxy_host)
    except OSError as exc:
        print(f"[ERROR] Proxy bind failed: {exc}", file=sys.stderr)
        return 1
    if proxy_port != preferred_proxy:
        print(f"[INFO] Port {preferred_proxy} unavailable — proxy listening on {proxy_port}")

    public = f"http://localhost:{proxy_port}" if proxy_port != 80 else "http://localhost"
    print("=" * 60)
    print("NexusCore suite (local — same routing as Docker proxy)")
    print("=" * 60)
    print(f"  Public entry  {public}/portals")
    print(f"  Engineering   {public}/dashboard")
    print(f"  Marketing     {public}/portals/marketing/")
    print(f"  Platform admin {public}/admin")
    print(f"  Activation    {public}/activation  (shared for now)")
    print(f"  Backends      127.0.0.1:{nxc_port}/{pn_port}/{np_port} (not for browser)")
    if _env_true("NCM_SKIP_ACTIVATION"):
        print("  [INFO] NCM_SKIP_ACTIVATION=1 — gate bypassed")
    print("Ctrl+C stops the proxy and all three processes.")
    print("=" * 60)

    procs: list[tuple[str, subprocess.Popen]] = []
    proxy = None
    try:
        procs.append(("NexusCore", _spawn("NexusCore", "nexuscore_app.py", str(nxc_port))))
        time.sleep(0.4)
        procs.append(("PrimeNet", _spawn("PrimeNet", "primenet_app.py", str(pn_port))))
        time.sleep(0.4)
        procs.append(("NexPulse", _spawn("NexPulse", "nexpulse_app.py", str(np_port))))

        print("[..] Waiting for backends…")
        nxc = ("127.0.0.1", nxc_port)
        pn = ("127.0.0.1", pn_port)
        np = ("127.0.0.1", np_port)
        for label, addr in (("NexusCore", nxc), ("PrimeNet", pn), ("NexPulse", np)):
            if not wait_for_upstream(*addr):
                print(f"[ERROR] {label} did not become ready on {addr[0]}:{addr[1]}", file=sys.stderr)
                _terminate(procs)
                return 1

        proxy = start_proxy(listen_host=proxy_host, listen_port=proxy_port, nxc=nxc, pn=pn, np=np)
        print(f"[OK] Proxy listening on {public}/")
        _open_browser(f"{public}/portals")
    except Exception as exc:
        print(f"[ERROR] Failed to start suite: {exc}", file=sys.stderr)
        if proxy is not None:
            proxy.shutdown()
        _terminate(procs)
        return 1

    def _on_signal(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        while True:
            for label, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[ERROR] {label} exited with code {code}")
                    proxy.shutdown()
                    _terminate(procs)
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down suite…")
        try:
            proxy.shutdown()
        except Exception:
            pass
        _terminate(procs)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
