"""Ingest Network Balance CSV exports into SQLite."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import config
from .balance_data import balance_root
from .balance_store import (
    db_has_data,
    ingest_csv_file,
    init_schema,
    recent_snapshots,
    snapshot_inventory,
    snapshot_needs_update,
)
from .file_discovery import parse_balance_filename

logger = logging.getLogger(__name__)


def _ingest_sources() -> list[Path]:
    roots = [balance_root()]
    archive = (os.environ.get("NETWORK_BALANCE_ARCHIVE_PATH") or "").strip()
    if archive:
        roots.append(Path(archive))
    return roots


def _date_window(
    *,
    lookback_days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[date, date]:
    if start_date and end_date:
        return min(start_date, end_date), max(start_date, end_date)
    end = end_date or date.today()
    days = lookback_days or config.BALANCE_INGEST_LOOKBACK_DAYS
    start = start_date or (end - timedelta(days=max(1, days) - 1))
    return start, end


def _collect_candidate_files(
    *,
    lookback_days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    vendors: list[str] | None = None,
) -> list[Path]:
    window_start, window_end = _date_window(
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
    )
    vendor_set = {v.lower() for v in (vendors or config.BALANCE_VENDORS)}
    seen: set[str] = set()
    files: list[Path] = []

    for root in _ingest_sources():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.csv")):
            vendor, file_date = parse_balance_filename(path)
            if not vendor or not file_date:
                continue
            if vendor not in vendor_set:
                continue
            if file_date < window_start or file_date > window_end:
                continue
            key = f"{vendor}|{file_date.isoformat()}|{path.name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            files.append(path)

    return files


def run_balance_ingest(
    *,
    lookback_days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    force: bool = False,
    vendors: list[str] | None = None,
) -> dict[str, Any]:
    """
    Scan Network Balance share/archive and ingest Nokia + Huawei CSVs into SQLite.

    Provide ``start_date`` + ``end_date`` for an explicit range, or ``lookback_days``
    ending today (default from config).
    """
    window_start, window_end = _date_window(
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
    )
    init_schema()

    summary: dict[str, Any] = {
        "success": True,
        "ingested": [],
        "skipped": [],
        "errors": [],
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "vendors": list(vendors or config.BALANCE_VENDORS),
    }

    if not _ingest_sources()[0].is_dir():
        summary["success"] = False
        summary["errors"].append(f"Network Balance folder not accessible: {balance_root()}")
        return summary

    for path in _collect_candidate_files(
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
        vendors=vendors,
    ):
        vendor, file_date = parse_balance_filename(path)
        if not vendor or not file_date:
            summary["skipped"].append({"file": str(path), "reason": "unrecognized vendor/date"})
            continue

        try:
            if not force and not snapshot_needs_update(vendor, file_date, path):
                summary["skipped"].append({
                    "file": str(path),
                    "vendor": vendor,
                    "date": file_date.isoformat(),
                    "reason": "already ingested",
                })
                continue

            result = ingest_csv_file(path, vendor=vendor, snapshot_date=file_date)
            summary["ingested"].append(result)
            logger.info(
                "Ingested balance %s %s (%d rows) from %s",
                vendor,
                file_date.isoformat(),
                result.get("row_count", 0),
                path.name,
            )
        except Exception as exc:
            logger.exception("Balance ingest failed for %s", path)
            summary["errors"].append({"file": str(path), "error": str(exc)})

    if summary["errors"]:
        summary["success"] = False
    summary["recent_snapshots"] = recent_snapshots(limit=20)
    summary["inventory"] = snapshot_inventory()
    summary["db_has_data"] = db_has_data()
    return summary


def ingest_status() -> dict[str, Any]:
    inventory = snapshot_inventory()
    return {
        "balance_path": str(balance_root()),
        "archive_path": (os.environ.get("NETWORK_BALANCE_ARCHIVE_PATH") or "").strip() or None,
        "db_path": inventory.get("db_path"),
        "db_has_data": db_has_data(),
        "nokia_in_db": db_has_data("nokia"),
        "huawei_in_db": db_has_data("huawei"),
        "inventory": inventory.get("vendors") or [],
        "recent_snapshots": recent_snapshots(limit=20),
    }
