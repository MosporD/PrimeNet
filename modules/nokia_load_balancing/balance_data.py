"""Network Balance data access — SQLite first, CSV share fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import config
from .smb_config import mount_point_active, smb_status_public
from .balance_store import (
    db_has_data,
    get_sectors_from_db,
    list_nok_sectors_from_db,
)
from .rules import highest_lowest_layer, normalize_throughput, parse_sector_id

def balance_root() -> Path:
    return Path(config.NETWORK_BALANCE_PATH)


def balance_configured() -> bool:
    if db_has_data():
        return True
    root = balance_root()
    try:
        return mount_point_active(str(root))
    except OSError:
        return False


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _file_path(folder: Path, day: date, vendor: str) -> Path:
    return folder / f"{day.strftime('%Y-%m-%d')} - {vendor}.csv"


def _normalize_sector(value: Any) -> str:
    return str(value or "").strip().replace("-", "_").upper()


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return None


def load_balance_df(
    target: datetime | date | None = None,
    *,
    vendor: str | None = None,
    lookback_days: int = 7,
) -> tuple[pd.DataFrame | None, Path | None, list[str]]:
    """
    Load the Network Balance CSV for ``target``, falling back to recent days.

    Returns (dataframe, path_used, warnings).
    """
    vendor = vendor or config.NETWORK_BALANCE_VENDOR
    folder = balance_root()
    warnings: list[str] = []

    if not folder.is_dir():
        smb = smb_status_public()
        hint = "Set NETWORK_BALANCE_PATH in .env if CSVs live on a local folder."
        if smb.get("enabled"):
            hint = (
                "Check NETWORK_BALANCE_SMB_HOST, USER, PASSWORD, DOMAIN in .env "
                f"and confirm the share is mounted at {smb.get('mount_point')}."
            )
        elif not str(folder).startswith("\\\\"):
            hint = (
                "On Linux, set NETWORK_BALANCE_SMB_ENABLED=1 and NETWORK_BALANCE_SMB_* in .env, "
                "or mount the share and set NETWORK_BALANCE_PATH."
            )
        warnings.append(f"Network Balance folder not accessible: {folder}. {hint}")
        return None, None, warnings

    start = _as_date(target) or date.today()
    for days_back in range(max(1, lookback_days)):
        candidate_date = start - timedelta(days=days_back)
        path = _file_path(folder, candidate_date, vendor)
        df = _load_csv(path)
        if df is not None:
            if days_back:
                warnings.append(f"Using balance file from {candidate_date.isoformat()} ({path.name}).")
            return df, path, warnings
        warnings.append(f"No file: {path.name}")

    warnings.append(
        f"No Network Balance CSV found for {vendor} in the last {lookback_days} day(s) under {folder}."
    )
    return None, None, warnings


def _row_throughput(row: pd.Series) -> dict[str, float | None]:
    raw = {}
    for layer, col in config.THROUGHPUT_COLUMNS.items():
        if col not in row.index:
            continue
        val = row.get(col)
        if pd.isna(val):
            continue
        try:
            raw[layer] = float(val)
        except (TypeError, ValueError):
            continue
    return normalize_throughput(raw)


def _sector_index(df: pd.DataFrame) -> dict[str, pd.Series]:
    if config.SECTOR_COLUMN not in df.columns:
        return {}
    out: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        key = _normalize_sector(row.get(config.SECTOR_COLUMN))
        if key:
            out[key] = row
    return out


def list_nok_sectors(
    target: datetime | date | None = None,
    vendor: str | None = None,
) -> dict[str, Any]:
    """Return NOK sectors with throughput summary (SQLite first)."""
    vendor = (vendor or config.NETWORK_BALANCE_VENDOR or "Nokia").strip() or "Nokia"
    day = _as_date(target)

    if config.BALANCE_PREFER_SQLITE and db_has_data(vendor.lower()):
        payload = list_nok_sectors_from_db(vendor.lower(), day)
        if payload.get("success"):
            payload["data_source"] = "sqlite"
            return payload

    df, path, warnings = load_balance_df(target, vendor=vendor)
    if df is None:
        return {
            "success": False,
            "sectors": [],
            "source_file": None,
            "data_source": "csv",
            "warnings": warnings,
            "errors": [warnings[-1] if warnings else "Network Balance data unavailable"],
        }

    if config.SECTOR_COLUMN not in df.columns:
        msg = f"Column '{config.SECTOR_COLUMN}' not found in {path.name if path else 'balance file'}"
        return {"success": False, "sectors": [], "source_file": str(path) if path else None, "data_source": "csv", "warnings": warnings, "errors": [msg]}

    if config.STATUS_COLUMN not in df.columns:
        msg = f"Column '{config.STATUS_COLUMN}' not found in {path.name if path else 'balance file'}"
        return {"success": False, "sectors": [], "source_file": str(path) if path else None, "data_source": "csv", "warnings": warnings, "errors": [msg]}

    status = df[config.STATUS_COLUMN].astype(str).str.strip().str.upper()
    nok_df = df[status == config.NOK_STATUS_VALUE].copy()

    sectors: list[dict[str, Any]] = []
    for _, row in nok_df.iterrows():
        sector_id = _normalize_sector(row.get(config.SECTOR_COLUMN))
        if not sector_id:
            continue
        throughput = _row_throughput(row)
        highest, lowest = highest_lowest_layer(throughput)
        sectors.append({
            "sector_id": sector_id,
            "throughput": throughput,
            "highest_layer": highest,
            "lowest_layer": lowest,
            "balancing_status": config.NOK_STATUS_VALUE,
        })

    sectors.sort(key=lambda s: s["sector_id"])
    return {
        "success": True,
        "sectors": sectors,
        "source_file": str(path) if path else None,
        "source_date": path.stem.split(" - ")[0] if path and " - " in path.stem else None,
        "data_source": "csv",
        "warnings": warnings,
        "errors": [],
    }


def sectors_from_balance(
    sector_ids: list[str],
    target: datetime | date | None = None,
    vendor: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """
    Look up requested sectors in Network Balance data.

    Returns (sectors_for_analyze, errors, source_label).
    """
    requested = []
    for sid in sector_ids:
        text = str(sid or "").strip()
        if not text:
            continue
        try:
            mrbts, letter = parse_sector_id(text)
            requested.append(f"{mrbts}_{letter}")
        except ValueError as exc:
            return [], [str(exc)], None

    if not requested:
        return [], ["Provide at least one sector id (e.g. 1201_A)."], None

    vendor_label = (vendor or config.NETWORK_BALANCE_VENDOR or "Nokia").strip() or "Nokia"
    vendor = vendor_label.lower()
    day = _as_date(target)

    if config.BALANCE_PREFER_SQLITE and db_has_data(vendor):
        sectors, warnings, meta = get_sectors_from_db(requested, vendor, day)
        if sectors:
            label = f"sqlite:{meta.get('snapshot_date')} ({meta.get('source_file')})"
            return sectors, warnings, label
        if warnings and not any("No Network Balance snapshot" in w for w in warnings):
            return sectors, warnings, meta.get("source_file") if meta else None

    df, path, warnings = load_balance_df(target, vendor=vendor_label)
    if df is None:
        return [], warnings or ["Network Balance data unavailable."], None

    if config.SECTOR_COLUMN not in df.columns:
        return [], [f"Column '{config.SECTOR_COLUMN}' not found in balance file."], str(path) if path else None

    index = _sector_index(df)
    sectors: list[dict[str, Any]] = []
    errors: list[str] = list(warnings)

    for sector_id in requested:
        row = index.get(sector_id)
        if row is None:
            errors.append(f"Sector {sector_id} not found in {path.name if path else 'balance file'}.")
            continue
        throughput = _row_throughput(row)
        highest, lowest = highest_lowest_layer(throughput)
        if not highest or not lowest:
            errors.append(
                f"Sector {sector_id}: need at least {config.MIN_ACTIVE_LAYERS} layers with throughput > 0."
            )
            continue
        sectors.append({
            "sector_id": sector_id,
            "throughput": throughput,
        })

    if not sectors:
        return [], errors or ["No valid sectors found in Network Balance data."], str(path) if path else None

    return sectors, errors, str(path) if path else None
