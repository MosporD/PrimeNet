"""
Master kill switch for ETL / sync / PM-Plus ingest pipelines.

Local laptop (default while developing)::

    NCM_ENABLE_ETL=0

Production / server (restore normal pull→load + scheduler)::

    NCM_ENABLE_ETL=1

Legacy: if ``NCM_ENABLE_ETL`` is unset, ``NCM_DISABLE_SCHEDULER=1`` still
forces pipelines off. When ``NCM_ENABLE_ETL=1``, Sync UI / pull / load are
allowed even if the web container has ``NCM_DISABLE_SCHEDULER=1`` (compose
keeps the cron out of the web process; the ``scheduler`` service runs it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    """Load project ``.env`` once so CLI scripts see NCM_ENABLE_ETL without a shell export."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[1]
        # override=False: explicit shell/compose env wins over .env
        load_dotenv(root / ".env", override=False)
    except Exception:
        pass


def _env_flag(key: str) -> str | None:
    _ensure_dotenv()
    raw = os.environ.get(key)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _falsy(raw: str) -> bool:
    return raw.strip().lower() in ("0", "false", "no", "off")


def etl_enabled() -> bool:
    """Return True only when ETL/sync pipelines are allowed to run.

    ``NCM_ENABLE_ETL`` is the master switch when set.
    ``NCM_DISABLE_SCHEDULER=1`` on web containers only means \"do not start the
    in-process cron\" — it must not block Sync UI mutations when
    ``NCM_ENABLE_ETL=1`` (scheduler runs as the separate compose service).
    """
    enable = _env_flag("NCM_ENABLE_ETL")
    if enable is not None:
        return _truthy(enable)

    # Legacy when NCM_ENABLE_ETL is unset.
    disable = _env_flag("NCM_DISABLE_SCHEDULER")
    if disable is not None and _truthy(disable):
        return False
    return True


def etl_disabled_reason() -> str:
    """Human-readable reason when ETL is off (empty string when enabled)."""
    if etl_enabled():
        return ""
    enable = _env_flag("NCM_ENABLE_ETL")
    if enable is not None and _falsy(enable):
        return "NCM_ENABLE_ETL=0 (set to 1 on the server to resume pipelines)"
    if enable is not None and not _truthy(enable):
        return f"NCM_ENABLE_ETL={enable!r} (expected 1/true/yes)"
    disable = _env_flag("NCM_DISABLE_SCHEDULER")
    if disable is not None and _truthy(disable):
        return "NCM_DISABLE_SCHEDULER=1 (set NCM_ENABLE_ETL=1 to allow Sync UI / pipelines)"
    return "ETL disabled"


def require_etl_enabled(*, stream=None) -> bool:
    """
    For CLI entry points. If ETL is disabled, print a short message and return False.
    Callers should ``sys.exit(0)`` (no-op success) so cron/compose does not flap.
    """
    if etl_enabled():
        return True
    out = stream or sys.stderr
    print(f"[etl-gate] skipped — {etl_disabled_reason()}", file=out)
    return False
