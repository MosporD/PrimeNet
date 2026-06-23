"""
Detect whether PM/group SQLite databases received new rows after a pipeline cycle.

Used by the SFTP watcher to re-run pull+load when files were fetched but ingest did not advance.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any

from pipeline.paths import iter_pm_raw_paths
from sync_config import (
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DB,
    NOKIA_PM_DAILY_DB,
)

_TABULAR_EXTS = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")


def _is_tabular(name: str) -> bool:
    low = name.lower()
    return low.endswith(_TABULAR_EXTS) and not name.startswith("~$")


def count_raw_tabular_files(scope: str) -> int:
    """Count staged tabular exports under raw/ for the given scope (hourly|daily)."""
    total = 0
    for vendor in ("nokia", "huawei"):
        for domain in ("cells", "groups"):
            for _tech, folder in iter_pm_raw_paths(vendor, domain, scope):
                if not os.path.isdir(folder):
                    continue
                total += sum(
                    1 for n in os.listdir(folder) if _is_tabular(n) and os.path.isfile(os.path.join(folder, n))
                )
    return total


def _db_fingerprint(db_path: str) -> dict[str, Any]:
    if not os.path.isfile(db_path):
        return {"row_count": 0, "max_timestamp": None, "tables": {}}

    out_tables: dict[str, dict[str, Any]] = {}
    total_rows = 0
    global_max: datetime | None = None

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            try:
                row_count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)
            except Exception:
                continue
            total_rows += row_count
            max_ts = _max_timestamp_in_table(conn, table)
            out_tables[table] = {"row_count": row_count, "max_timestamp": max_ts}
            if max_ts is not None and (global_max is None or max_ts > global_max):
                global_max = max_ts
    finally:
        conn.close()

    return {
        "row_count": total_rows,
        "max_timestamp": global_max.isoformat() if global_max else None,
        "tables": out_tables,
    }


def _parse_db_timestamp(raw) -> datetime | None:
    """Parse PM DB timestamps (dd/mm/yyyy, optional trailing DST label)."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw

    s = str(raw).strip()
    if not s:
        return None

    # Nokia exports often suffix local time with "DST" (not a real IANA zone).
    if s.upper().endswith("DST"):
        s = s[:-3].strip()

    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _max_timestamp_in_table(conn: sqlite3.Connection, table: str) -> datetime | None:
    cols = [r[1].lower() for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    candidates = [
        c
        for c in cols
        if c in ("period_start_time", "time", "date", "timestamp", "datetime")
        or "time" in c
        or c.endswith("_time")
    ]
    if not candidates:
        return None
    col = candidates[0]
    try:
        raw = conn.execute(
            f'SELECT MAX("{col}") FROM "{table}" WHERE "{col}" IS NOT NULL AND TRIM(CAST("{col}" AS TEXT)) != \'\''
        ).fetchone()[0]
    except Exception:
        return None
    if raw is None:
        return None
    return _parse_db_timestamp(raw)


def capture_ingest_snapshot() -> dict[str, dict[str, Any]]:
    """Fingerprint hourly + daily PM/group databases."""
    return {
        "hourly_nokia_cells": _db_fingerprint(NOKIA_PM_DB),
        "hourly_huawei_cells": _db_fingerprint(HUAWEI_PM_DB),
        "hourly_nokia_groups": _db_fingerprint(NOKIA_GROUPS_DB),
        "hourly_huawei_groups": _db_fingerprint(HUAWEI_GROUPS_DB),
        "daily_nokia_cells": _db_fingerprint(NOKIA_PM_DAILY_DB),
        "daily_huawei_cells": _db_fingerprint(HUAWEI_PM_DAILY_DB),
        "daily_nokia_groups": _db_fingerprint(NOKIA_GROUPS_DAILY_DB),
        "daily_huawei_groups": _db_fingerprint(HUAWEI_GROUPS_DAILY_DB),
    }


def snapshot_advanced(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """True when row counts or max timestamp increased between snapshots."""
    if int(after.get("row_count") or 0) > int(before.get("row_count") or 0):
        return True
    b_ts = before.get("max_timestamp")
    a_ts = after.get("max_timestamp")
    if a_ts and (not b_ts or str(a_ts) > str(b_ts)):
        return True
    return False


def scope_ingest_advanced(before_all: dict, after_all: dict, scope: str) -> bool:
    prefix = f"{scope}_"
    for key, after_fp in after_all.items():
        if not key.startswith(prefix):
            continue
        before_fp = before_all.get(key) or {}
        if snapshot_advanced(before_fp, after_fp):
            return True
    return False


def scopes_needing_retry(
    before_all: dict,
    after_all: dict,
    *,
    hourly_raw_files: int,
    daily_raw_files: int,
    ran_hourly: bool,
    ran_daily: bool,
) -> list[str]:
    """
    Return scopes ('hourly', 'daily') that ran pull/load but did not advance any DB fingerprint
    while raw files were still present (ingest likely failed or was filtered out).
    """
    out: list[str] = []
    if ran_hourly and hourly_raw_files > 0 and not scope_ingest_advanced(before_all, after_all, "hourly"):
        out.append("hourly")
    if ran_daily and daily_raw_files > 0 and not scope_ingest_advanced(before_all, after_all, "daily"):
        out.append("daily")
    return out
