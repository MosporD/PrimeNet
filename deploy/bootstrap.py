"""
One-shot application bootstrap: data DB migrations, app user DB, optional scheduler.

Run before Gunicorn in containers (entrypoint) or on first import for local dev.
"""

from __future__ import annotations

import os
import sys


def _env_true(key: str, default: bool = False) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def should_start_scheduler() -> bool:
    if _env_true("NCM_DISABLE_SCHEDULER"):
        return False
    if _env_true("NCM_RUN_SCHEDULER"):
        return True
    # Container web tier: scheduler runs in a separate service.
    if _env_true("NCM_CONTAINER"):
        return False
    # Flask dev reloader: only start in the parent process.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return False
    return True


def run_bootstrap(*, start_scheduler: bool | None = None) -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from core.activation_gate import install_sqlite_gate, is_activated, require_activation

    install_sqlite_gate()
    require_activation()

    from modules.sync.db_migration import run_migrations
    from database_enhanced import init_db, create_admin_user

    try:
        run_migrations()
        print("[OK] Data databases migrated successfully")
    except Exception as exc:
        print(f"[WARNING] Data DB migrations: {exc}")

    try:
        init_db()
        create_admin_user()
        print("[OK] App user database initialized successfully")
    except Exception as exc:
        print(f"[WARNING] App database initialization: {exc}")

    if start_scheduler is None:
        start_scheduler = should_start_scheduler()
    if not start_scheduler:
        if _env_true("NCM_DISABLE_SCHEDULER"):
            print("[INFO] Sync scheduler disabled (NCM_DISABLE_SCHEDULER=1)")
        return

    from modules.sync.scheduler import start_scheduler as _start

    try:
        _start()
        print("[OK] Sync scheduler started")
    except Exception as exc:
        print(f"[WARNING] Sync scheduler could not start: {exc}")


def run_app_bootstrap_if_enabled() -> None:
    if os.getenv("NCM_BOOTSTRAP_ON_IMPORT", "1").strip().lower() in ("0", "false", "no"):
        return
    run_bootstrap()


if __name__ == "__main__":
    run_bootstrap(start_scheduler=should_start_scheduler())
