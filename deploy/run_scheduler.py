"""
Long-running scheduler worker for Docker Compose ``scheduler`` service.

Keeps APScheduler alive without running the HTTP server.
"""

from __future__ import annotations

import os
import signal
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("NCM_CONTAINER", "1")
os.environ.setdefault("NCM_RUN_SCHEDULER", "1")
os.environ.setdefault("NCM_DISABLE_SCHEDULER", "0")
os.environ.setdefault("NCM_BOOTSTRAP_ON_IMPORT", "0")

from core.activation_gate import install_sqlite_gate  # noqa: E402

install_sqlite_gate()

from deploy.bootstrap import run_bootstrap  # noqa: E402


def main() -> None:
    print("[OK] Starting PrimeNet sync scheduler worker")
    run_bootstrap(start_scheduler=True)

    stop = False

    def _handle_signal(signum, _frame):
        nonlocal stop
        print(f"[INFO] Scheduler worker received signal {signum}, shutting down")
        stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop:
        time.sleep(60)


if __name__ == "__main__":
    main()
