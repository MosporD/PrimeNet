"""Ingest Network Balance CSV exports into SQLite."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import config
from .balance_data import balance_root
from .smb_config import smb_status_public
from .balance_store import (
    daily_status_summary,
    db_has_data,
    ingest_csv_file,
    init_schema,
    list_snapshots_in_range,
    recent_snapshots,
    snapshot_inventory,
    snapshot_needs_update,
)
from .file_discovery import parse_balance_filename

logger = logging.getLogger(__name__)

_last_ingest_result: dict[str, Any] | None = None


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
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")

    global _last_ingest_result
    _last_ingest_result = summary
    return summary


def _expected_filename(day: date, vendor: str) -> str:
    label = vendor.capitalize() if vendor.lower() == "nokia" else vendor.title()
    return f"{day.isoformat()} - {label}.csv"


def _scan_share_csvs(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (recognized files, unrecognized CSV stems)."""
    recognized: list[dict[str, Any]] = []
    unrecognized: list[dict[str, Any]] = []
    if not root.is_dir():
        return recognized, unrecognized
    try:
        paths = sorted(root.glob("*.csv"))
    except OSError as exc:
        return recognized, [{"file": str(root), "error": str(exc)}]

    for path in paths:
        vendor, file_date = parse_balance_filename(path)
        if vendor and file_date:
            recognized.append({
                "file": str(path),
                "name": path.name,
                "vendor": vendor,
                "date": file_date.isoformat(),
                "size_bytes": path.stat().st_size if path.is_file() else None,
            })
        else:
            unrecognized.append({"file": str(path), "name": path.name})
    return recognized, unrecognized


def ingest_diagnostics(
    *,
    lookback_days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """
    Preflight check: trace CSV share → SQLite → trend tables without importing.
    """
    window_start, window_end = _date_window(
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
    )
    root = balance_root()
    archive_raw = (os.environ.get("NETWORK_BALANCE_ARCHIVE_PATH") or "").strip()
    archive = Path(archive_raw) if archive_raw else None
    smb = smb_status_public()
    inventory = snapshot_inventory()
    db_path = inventory.get("db_path")

    share_accessible = root.is_dir()
    share_csv_count = 0
    share_error: str | None = None
    if share_accessible:
        try:
            share_csv_count = len(list(root.glob("*.csv")))
        except OSError as exc:
            share_error = str(exc)
            share_accessible = False
    else:
        try:
            root.exists()
            share_error = f"Path exists but is not a directory: {root}"
        except OSError as exc:
            share_error = str(exc)

    recognized, unrecognized = _scan_share_csvs(root)
    archive_files: list[dict[str, Any]] = []
    if archive and archive.is_dir():
        archive_files, _ = _scan_share_csvs(archive)

    in_window = [
        f for f in recognized
        if window_start <= date.fromisoformat(f["date"]) <= window_end
    ]

    db_snapshots = list_snapshots_in_range(window_start, window_end)
    db_by_key = {
        f"{s['vendor']}|{s['snapshot_date']}": s for s in db_snapshots
    }

    coverage: list[dict[str, Any]] = []
    day = window_start
    while day <= window_end:
        for vendor in config.BALANCE_VENDORS:
            key = f"{vendor}|{day.isoformat()}"
            expected = _expected_filename(day, vendor)
            file_match = next(
                (
                    f for f in in_window
                    if f["vendor"] == vendor and f["date"] == day.isoformat()
                ),
                None,
            )
            canonical = root / expected
            canonical_exists = canonical.is_file()
            snapshot = db_by_key.get(key)
            if not snapshot and not file_match and not canonical_exists:
                status = "missing"
                detail = "No CSV on share and not in database"
            elif snapshot:
                status = "in_db"
                detail = f"{snapshot.get('row_count', 0)} rows ingested"
            elif file_match or canonical_exists:
                status = "pending"
                detail = "CSV available — run Sync to database"
            else:
                status = "missing"
                detail = "Not on share or in database"

            coverage.append({
                "date": day.isoformat(),
                "vendor": vendor,
                "expected_file": expected,
                "canonical_exists": canonical_exists,
                "discovered_file": (file_match or {}).get("name"),
                "db_status": status,
                "detail": detail,
                "row_count": (snapshot or {}).get("row_count"),
            })
        day += timedelta(days=1)

    trend_nokia = daily_status_summary(window_start, window_end, vendor="nokia")
    trend_huawei = daily_status_summary(window_start, window_end, vendor="huawei")

    steps: list[dict[str, Any]] = []

    if smb.get("enabled"):
        smb_ok = bool(smb.get("configured") and smb.get("mounted"))
        steps.append({
            "id": "smb",
            "label": "SMB share mounted",
            "status": "ok" if smb_ok else "error",
            "detail": (
                f"{smb.get('host')}/{smb.get('share')} → {smb.get('mount_point')}"
                if smb_ok
                else (
                    "SMB enabled but not mounted — check NETWORK_BALANCE_SMB_* in .env"
                    if smb.get("configured")
                    else "SMB enabled but host/user/password not configured"
                )
            ),
        })
    else:
        steps.append({
            "id": "share",
            "label": "Network Balance folder reachable",
            "status": "ok" if share_accessible else "error",
            "detail": (
                f"{share_csv_count} CSV file(s) under {root}"
                if share_accessible
                else share_error or f"Folder not accessible: {root}"
            ),
        })

    steps.append({
        "id": "csvs",
        "label": "CSV exports found in date range",
        "status": "ok" if in_window else ("warn" if share_accessible else "error"),
        "detail": (
            f"{len(in_window)} recognized file(s) for {window_start} → {window_end}"
            if in_window
            else f"No Nokia/Huawei CSVs parsed for {window_start} → {window_end}"
        ),
    })

    db_ok = bool(db_path and Path(str(db_path)).parent.exists())
    steps.append({
        "id": "database",
        "label": "SQLite database ready",
        "status": "ok" if db_ok else "error",
        "detail": str(db_path) if db_path else "Database path not configured",
    })

    ingested_days = len({s["snapshot_date"] for s in db_snapshots})
    pending = [c for c in coverage if c["db_status"] == "pending"]
    missing = [c for c in coverage if c["db_status"] == "missing"]
    if db_snapshots:
        ingest_status_label = "ok" if not pending and not missing else "warn"
        ingest_detail = f"{len(db_snapshots)} snapshot(s) in range ({ingested_days} day(s))"
        if pending:
            ingest_detail += f" · {len(pending)} pending sync"
        if missing:
            ingest_detail += f" · {len(missing)} gaps"
    else:
        ingest_status_label = "error"
        ingest_detail = "No snapshots in range — run Sync to database"
    steps.append({
        "id": "ingest",
        "label": "Snapshots ingested for range",
        "status": ingest_status_label,
        "detail": ingest_detail,
    })

    trend_ready = bool(trend_nokia or trend_huawei)
    steps.append({
        "id": "trend",
        "label": "Balancing trend tables populated",
        "status": "ok" if trend_ready else "error",
        "detail": (
            f"Nokia {len(trend_nokia)} status group(s), Huawei {len(trend_huawei)}"
            if trend_ready
            else "Load trend will be empty until snapshots are ingested"
        ),
    })

    blocking: list[str] = []
    warnings: list[str] = []
    for step in steps:
        if step["status"] == "error":
            blocking.append(f"{step['label']}: {step['detail']}")
    if unrecognized:
        warnings.append(
            f"{len(unrecognized)} CSV(s) on share could not be parsed (vendor/date not recognized)"
        )

    return {
        "success": not blocking,
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "balance_path": str(root),
        "archive_path": str(archive) if archive else None,
        "smb": smb,
        "share_accessible": share_accessible,
        "share_csv_count": share_csv_count,
        "share_error": share_error,
        "db_path": db_path,
        "db_has_data": db_has_data(),
        "inventory": inventory.get("vendors") or [],
        "steps": steps,
        "blocking_issues": blocking,
        "warnings": warnings,
        "discovered_files": in_window,
        "unrecognized_files": unrecognized[:50],
        "archive_files_in_range": [
            f for f in archive_files
            if window_start <= date.fromisoformat(f["date"]) <= window_end
        ],
        "coverage": coverage,
        "last_sync": _last_ingest_result,
    }


def ingest_status() -> dict[str, Any]:
    inventory = snapshot_inventory()
    return {
        "balance_path": str(balance_root()),
        "archive_path": (os.environ.get("NETWORK_BALANCE_ARCHIVE_PATH") or "").strip() or None,
        "smb": smb_status_public(),
        "db_path": inventory.get("db_path"),
        "db_has_data": db_has_data(),
        "nokia_in_db": db_has_data("nokia"),
        "huawei_in_db": db_has_data("huawei"),
        "inventory": inventory.get("vendors") or [],
        "recent_snapshots": recent_snapshots(limit=20),
        "last_sync": _last_ingest_result,
    }

