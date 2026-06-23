"""License service configuration (environment / .env)."""

from __future__ import annotations

import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


LICENSE_PERIOD_DAYS = _env_int("LICENSE_PERIOD_DAYS", 30)
LICENSE_HOST = _env("LICENSE_HOST", "0.0.0.0")
LICENSE_PORT = _env_int("LICENSE_PORT", 5055)
LICENSE_DATA_DIR = Path(_env("LICENSE_DATA_DIR", str(SERVICE_ROOT / "data")))

OPERATOR_PASSWORD = _env("LICENSE_OPERATOR_PASSWORD")
PRIVATE_KEY_PATH = Path(_env("LICENSE_PRIVATE_KEY_PATH", str(LICENSE_DATA_DIR / "private.pem")))
PUBLIC_KEY_PATH = Path(_env("LICENSE_PUBLIC_KEY_PATH", str(LICENSE_DATA_DIR / "public.pem")))

API_TOKEN = _env("LICENSE_API_TOKEN")  # optional Bearer for admin endpoints
