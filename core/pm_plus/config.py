"""Configuration for Performance Explorer Plus (Nokia NBI → warehouse)."""

from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(_env("NCM_DATA_ROOT") or str(PROJECT_ROOT))
STAGING_DIR = Path(_env("PM_PLUS_STAGING_DIR") or str(DATA_ROOT / "raw" / "pm_plus" / "nokia"))
SQLITE_PATH = Path(
    _env("PM_PLUS_SQLITE_PATH") or str(DATA_ROOT / "databases" / "pm_plus" / "pm_plus.db")
)

# Prefer dedicated URL; fall back to NCM_DATABASE_URL when set.
PM_PLUS_DATABASE_URL = _env("PM_PLUS_DATABASE_URL") or _env("NCM_DATABASE_URL")
PM_PLUS_SCHEMA = _env("PM_PLUS_SCHEMA") or "pm_plus"

NOKIA_PM_FTP_USER = _env("NOKIA_PM_FTP_USER") or "ftpuser"
NOKIA_PM_FTP_PRIMARY_HOST = _env("NOKIA_PM_FTP_PRIMARY_HOST") or "10.119.219.24"
NOKIA_PM_FTP_BACKUP_HOST = _env("NOKIA_PM_FTP_BACKUP_HOST") or "10.119.219.25"
NOKIA_PM_FTP_PRIMARY_PASSWORD = _env("NOKIA_PM_FTP_PRIMARY_PASSWORD")
NOKIA_PM_FTP_BACKUP_PASSWORD = _env("NOKIA_PM_FTP_BACKUP_PASSWORD")
NOKIA_PM_FTP_PORT = _env_int("NOKIA_PM_FTP_PORT", 22)

# Absolute remote roots (leading slash). Streams map to local ledger labels 14/15.
REMOTE_PATHS: dict[str, str] = {
    "14": _env("NOKIA_PM_FTP_PATH_14")
    or "/var/opt/oss/global/ftirpuser/pm/rc02vm14/raw/",
    "15": _env("NOKIA_PM_FTP_PATH_15")
    or "/var/opt/oss/global/ftirpuser/pm/rc02vm15/raw/",
}

DOWNLOAD_WORKERS = max(1, min(32, _env_int("PM_PLUS_DOWNLOAD_WORKERS", 8)))
INGEST_WORKERS = max(1, min(32, _env_int("PM_PLUS_INGEST_WORKERS", 8)))
POLL_INTERVAL_SEC = max(5, _env_int("PM_PLUS_POLL_INTERVAL_SEC", 30))
RAW_RETENTION_HOURS = max(1, _env_int("PM_PLUS_RAW_RETENTION_HOURS", 6))
# ROP buffer only (day is rebuilt from raw ROP, not from hour)
FACT_15M_RETENTION_DAYS = max(1, _env_int("PM_PLUS_FACT_15M_RETENTION_DAYS", 3))
FACT_HOUR_RETENTION_DAYS = max(1, _env_int("PM_PLUS_FACT_HOUR_RETENTION_DAYS", 14))
FACT_DAY_RETENTION_DAYS = max(1, _env_int("PM_PLUS_FACT_DAY_RETENTION_DAYS", 90))
FACT_WEEK_RETENTION_DAYS = max(1, _env_int("PM_PLUS_FACT_WEEK_RETENTION_DAYS", 366))
FACT_MONTH_RETENTION_MONTHS = max(1, _env_int("PM_PLUS_FACT_MONTH_RETENTION_MONTHS", 12))
FACT_YEAR_RETENTION_YEARS = max(1, _env_int("PM_PLUS_FACT_YEAR_RETENTION_YEARS", 10))
DELETE_LOCAL_AFTER_INGEST = _env_bool("PM_PLUS_DELETE_LOCAL_AFTER_INGEST", True)


def use_postgres() -> bool:
    return bool(PM_PLUS_DATABASE_URL)


def ftp_hosts() -> list[dict]:
    """Ordered host attempts: primary then backup."""
    hosts = [
        {
            "label": "primary",
            "host": NOKIA_PM_FTP_PRIMARY_HOST,
            "port": NOKIA_PM_FTP_PORT,
            "username": NOKIA_PM_FTP_USER,
            "password": NOKIA_PM_FTP_PRIMARY_PASSWORD,
        },
        {
            "label": "backup",
            "host": NOKIA_PM_FTP_BACKUP_HOST,
            "port": NOKIA_PM_FTP_PORT,
            "username": NOKIA_PM_FTP_USER,
            "password": NOKIA_PM_FTP_BACKUP_PASSWORD,
        },
    ]
    return [h for h in hosts if h["host"]]
