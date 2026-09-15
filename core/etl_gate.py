"""
Master kill switch for ETL / sync / PM-Plus ingest pipelines.

Local laptop (default while developing)::

    NCM_ENABLE_ETL=0

Production / server (restore normal pull→load + scheduler)::

    NCM_ENABLE_ETL=1

Legacy: ``NCM_DISABLE_SCHEDULER=1`` still forces pipelines off.
If ``NCM_ENABLE_ETL`` is unset, behaviour follows legacy
(enabled unless ``NCM_DISABLE_SCHEDULER``).
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
    """Return True only when ETL/sync pipelines are allowed to run."""
    disable = _env_flag("NCM_DISABLE_SCHEDULER")
    if disable is not None and _truthy(disable):
        return False

    enable = _env_flag("NCM_ENABLE_ETL")
    if enable is not None:
        return _truthy(enable)

    # Unset NCM_ENABLE_ETL → legacy default (on, unless DISABLE above).
    return True


def etl_disabled_reason() -> str:
    """Human-readable reason when ETL is off (empty string when enabled)."""
    if etl_enabled():
        return ""
    disable = _env_flag("NCM_DISABLE_SCHEDULER")
    if disable is not None and _truthy(disable):
        return "NCM_DISABLE_SCHEDULER=1"
    enable = _env_flag("NCM_ENABLE_ETL")
    if enable is not None and _falsy(enable):
        return "NCM_ENABLE_ETL=0 (set to 1 on the server to resume pipelines)"
    if enable is not None and not _truthy(enable):
        return f"NCM_ENABLE_ETL={enable!r} (expected 1/true/yes)"
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
