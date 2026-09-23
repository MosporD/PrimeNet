"""Local suite launcher — start NexusCore + PrimeNet + NexPulse together.

Usage::

    python app.py

Starts three processes on ports 8000 / 8001 / 8002 for local testing.
This launcher does **not** start nginx. The single-port reverse proxy is only
used with Docker Compose (``deploy/nginx.conf`` + ``proxy`` service).

Activation is **shared for testing**: unlock once at
http://localhost:8001/activation and all platforms open. Per-platform activation
comes later (``NCM_SHARED_ACTIVATION=0`` to opt a process out of the shared gate).

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
    """Env for suite children — always three-port local URLs (not Docker proxy mode)."""
    env = os.environ.copy()
    env.setdefault("NCM_DISABLE_LIVE_LOGGER_TERMINAL", "1")
    env.setdefault("NCM_DISABLE_AUTO_BROWSER", "1")
    env.setdefault("NCM_SHARED_ACTIVATION", "1")
    # Force multi-port local origins even if .env is set up for Docker proxy.
    env["NEXUS_PUBLIC_URL_FROM_REQUEST"] = "0"
    env["NEXUS_PUBLIC_URL"] = ""
    env["NEXUSCORE_PUBLIC_URL"] = "http://localhost:8000"
    env["PRIMENET_PUBLIC_URL"] = "http://localhost:8001"
    env["NEXPULSE_PUBLIC_URL"] = "http://localhost:8002"
    env["NEXUS_COOKIE_DOMAIN"] = ""
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
    print(f"[OK] {label} pid={proc.pid}  http://localhost:{port}")
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


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except ImportError:
        pass

    nxc_port = os.getenv("NEXUSCORE_PORT", "8000")
    pn_port = os.getenv("PRIMENET_PORT", "8001")
    np_port = os.getenv("NEXPULSE_PORT", "8002")

    print("=" * 60)
    print("NexusCore suite (local test launcher)")
    print("=" * 60)
    print(f"  NexusCore  http://localhost:{nxc_port}/portals")
    print(f"  PrimeNet   http://localhost:{pn_port}/dashboard")
    print(f"  NexPulse   http://localhost:{np_port}/portals/marketing/")
    print(f"  Activation http://localhost:{pn_port}/activation  (shared for now)")
    if _env_true("NCM_SKIP_ACTIVATION"):
        print("  [INFO] NCM_SKIP_ACTIVATION=1 — gate bypassed")
    print("Ctrl+C stops all three processes.")
    print("=" * 60)

    procs: list[tuple[str, subprocess.Popen]] = []
    try:
        procs.append(("NexusCore", _spawn("NexusCore", "nexuscore_app.py", nxc_port)))
        time.sleep(0.4)
        procs.append(("PrimeNet", _spawn("PrimeNet", "primenet_app.py", pn_port)))
        time.sleep(0.4)
        procs.append(("NexPulse", _spawn("NexPulse", "nexpulse_app.py", np_port)))
    except Exception as exc:
        print(f"[ERROR] Failed to start suite: {exc}", file=sys.stderr)
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
                    _terminate(procs)
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down suite…")
        _terminate(procs)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
