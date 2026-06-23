"""
Load repeater device records from manual Excel/CSV files under network-map/repeater.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REPEATER_DIRS = (
    _PROJECT_ROOT / "network-map" / "repeater",
    Path(__file__).resolve().parent / "Repeater Data",
)

_TABULAR_EXT = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")

# Normalized field -> spreadsheet column aliases (first match wins).
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "refcode": ("refcode", "ref code", "wo", "work order"),
    "site_name": ("site_name", "site name", "sitename"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "long", "lng", "lon"),
    "repeater_type": ("repeater_type", "repeater type", "type"),
    "manufacturer": ("repeater_manufacture", "repeater manufacture", "manufacturer", "vendor"),
    "repeater_model": ("repeater_model", "repeater model", "model"),
    "repeater_number": ("repeater_number", "repeater number", "rep number"),
    "status": ("status",),
    "remedy_action": ("remedy_action", "remedy action", "action"),
    "neighborhood": ("neighborhood", "neighbourhood"),
    "address": ("address",),
    "category": ("category",),
    "subcategory": ("subcategory", "sub category"),
    "outdoor_antenna": ("out_door_antenna", "outdoor_antenna", "out door antenna"),
    # Rep_Serial_Num is the unique physical repeater id (not Refcode / work orders).
    "serial_number": ("rep_serial_num",),
    "floor_no": ("floor_no", "floor no", "floor"),
    "assign_to": ("assign_to", "assign to", "technician"),
    "contact_number": ("contact_number", "contact number", "mobile number", "phone"),
    "requester": ("requester", "customer"),
    "customer_name_arabic": (
        "customer_name_arabic",
        "customer name in arabic",
        "customer name arabic",
    ),
    "technician_notes": ("technician_notes", "technician notes"),
    "solution_type": ("solution_type", "solution type"),
    "submit_date": ("submit_date", "submit date"),
}

_cache: dict[str, Any] = {"path": None, "mtime": None, "rows": []}


def repeater_data_directories() -> list[Path]:
    return list(_REPEATER_DIRS)


def _normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    norm = {_normalize_header(c): c for c in df.columns}
    out: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in norm:
                out[field] = norm[key]
                break
    if "contact_number" not in out:
        for ncol, orig in norm.items():
            if "contact" in ncol and "number" in ncol:
                out["contact_number"] = orig
                break
    return out


def supported_rats_from_type(repeater_type: str) -> str:
    """Derive supported RAT list from spreadsheet Repeater_Type (e.g. 2G+3G, 3G only)."""
    raw = (repeater_type or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\s+", "", raw.lower())
    if compact in ("non", "none", "n/a"):
        return ""
    rats: list[str] = []
    if "2g" in compact:
        rats.append("2G")
    if "3g" in compact:
        rats.append("3G")
    if "4g" in compact or "lte" in compact:
        rats.append("4G")
    if "5g" in compact or compact.startswith("nr"):
        rats.append("5G")
    return ", ".join(rats) if rats else raw


_CLEANED_STEM_SUFFIX = "_cleaned"


def _is_cleaned_export(path: Path) -> bool:
    return path.stem.lower().endswith(_CLEANED_STEM_SUFFIX)


def _cleaned_export_path(source: Path) -> Path:
    stem = source.stem
    if stem.lower().endswith(_CLEANED_STEM_SUFFIX):
        return source
    return source.with_name(f"{stem}{_CLEANED_STEM_SUFFIX}{source.suffix}")


def _iter_repeater_files() -> list[Path]:
    out: list[Path] = []
    for directory in _REPEATER_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in _TABULAR_EXT and not path.name.startswith("~$"):
                out.append(path)
    return out


def _find_latest_raw_repeater_file() -> Path | None:
    candidates = [p for p in _iter_repeater_files() if not _is_cleaned_export(p)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _find_latest_repeater_file() -> Path | None:
    """Latest raw export (request log), not the derived cleaned file."""
    return _find_latest_raw_repeater_file()


def _read_tabular(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, dtype=str, engine="openpyxl")
    if ext == ".xls":
        return pd.read_excel(path, dtype=str, engine="xlrd")
    # cp1256 before latin-1 — Jordan/Arabic exports are often Windows Arabic, not Latin-1.
    for encoding in ("utf-8-sig", "utf-8", "cp1256", "cp1252"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=encoding)
            if encoding != "utf-8" and encoding != "utf-8-sig":
                sample = " ".join(str(v) for v in df.head(20).astype(str).values.flatten()[:200])
                if "\ufffd" in sample:
                    continue
            return df
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str, encoding="cp1256")


def _clean_text(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    if s.lower() in ("#n/a", "nan", "none"):
        return ""
    return s


def _parse_submit_date(val: object) -> pd.Timestamp | None:
    """Parse Submit_Date (often DD/MM/YYYY in exports)."""
    s = _clean_text(val)
    if not s:
        return None
    ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if ts is None or pd.isna(ts):
        return None
    return ts


def _rep_serial_num_column(df: pd.DataFrame) -> str:
    """Resolve Rep_Serial_Num column (required for deduplication)."""
    cols = _resolve_columns(df)
    serial_col = cols.get("serial_number")
    if serial_col:
        return serial_col
    norm = {_normalize_header(c): c for c in df.columns}
    if "rep_serial_num" in norm:
        return norm["rep_serial_num"]
    raise ValueError(
        "Missing Rep_Serial_Num column. Expected header Rep_Serial_Num (repeater unique id)."
    )


def dedupe_repeater_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse duplicate service requests to one row per Rep_Serial_Num (latest Submit_Date).
    Rows with an empty serial are kept as-is (requests not yet tied to a repeater).
    """
    if df.empty:
        return df.copy()

    serial_col = _rep_serial_num_column(df)
    cols = _resolve_columns(df)
    date_col = cols.get("submit_date")

    work = df.copy()
    work["_row_idx"] = range(len(work))
    if date_col:
        work["_sort_date"] = work[date_col].map(
            lambda v: int(ts.value) if (ts := _parse_submit_date(v)) is not None else -1
        )
    else:
        work["_sort_date"] = -1

    serials = work[serial_col].map(_clean_text)
    has_serial = serials != ""
    keep: list[int] = list(work.loc[~has_serial, "_row_idx"].astype(int))

    with_serial = work.loc[has_serial].copy()
    with_serial["_serial_key"] = serials.loc[has_serial].str.casefold()
    for _, grp in with_serial.groupby("_serial_key", sort=False):
        best = grp.sort_values(["_sort_date", "_row_idx"]).iloc[-1]
        keep.append(int(best["_row_idx"]))

    keep = sorted(set(keep))
    return df.iloc[keep].copy().reset_index(drop=True)


def write_cleaned_repeater_sheet(
    source: Path | None = None,
    dest: Path | None = None,
) -> tuple[Path, int, int]:
    """
    Write deduplicated repeater sheet next to the source file.
    Returns (output_path, input_rows, output_rows).
    """
    source = source or _find_latest_raw_repeater_file()
    if source is None:
        raise FileNotFoundError("No repeater spreadsheet found in network-map/repeater")

    dest = dest or _cleaned_export_path(source)
    df = _read_tabular(source)
    cleaned = dedupe_repeater_dataframe(df)

    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = dest.suffix.lower()

    def _write(target: Path) -> None:
        if ext in (".xlsx", ".xlsm"):
            cleaned.to_excel(target, index=False, engine="openpyxl")
        elif ext == ".xls":
            cleaned.to_excel(target, index=False)
        else:
            cleaned.to_csv(target, index=False, encoding="utf-8-sig")

    try:
        _write(dest)
    except PermissionError:
        alt = dest.with_name(f"{dest.stem}_new{dest.suffix}")
        _write(alt)
        dest = alt

    return dest, len(df), len(cleaned)


def ensure_cleaned_repeater_sheet(source: Path | None = None) -> Path:
    """Build or refresh the *_cleaned* file when the raw export is newer."""
    source = source or _find_latest_raw_repeater_file()
    if source is None:
        raise FileNotFoundError("No repeater spreadsheet found in network-map/repeater")

    dest = _cleaned_export_path(source)
    if dest.exists() and dest.stat().st_mtime >= source.stat().st_mtime:
        return dest
    write_cleaned_repeater_sheet(source, dest)
    return dest


def _row_recency_key(rec: dict) -> tuple[int, int]:
    """Sort key: latest submit_date wins; ties keep later source row."""
    ts = _parse_submit_date(rec.get("submit_date"))
    ordinal = int(ts.value) if ts is not None else -1
    return (ordinal, rec.get("_source_row", 0))


def _dedupe_repeater_rows(rows: list[dict]) -> list[dict]:
    """
    Spreadsheet rows are service requests; Rep_Serial_Num is the unique repeater id.
    Keep one record per serial (latest Submit_Date). Rows without a serial are kept.
    """
    by_serial: dict[str, list[dict]] = {}
    no_serial: list[dict] = []

    for rec in rows:
        sn = (rec.get("serial_number") or "").strip()
        if sn:
            by_serial.setdefault(sn.casefold(), []).append(rec)
        else:
            no_serial.append(rec)

    out: list[dict] = []
    for group in by_serial.values():
        best = max(group, key=_row_recency_key)
        out.append(_finalize_repeater_record(best))

    for rec in no_serial:
        out.append(_finalize_repeater_record(rec))

    return out


def _finalize_repeater_record(rec: dict) -> dict:
    """Drop loader-only fields and set stable map id from serial when available."""
    rec = {k: v for k, v in rec.items() if k != "_source_row"}
    serial = (rec.get("serial_number") or "").strip()
    if serial:
        rec["repeater_id"] = serial
    return rec


def _parse_coord(val: object) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not (-90 <= v <= 90) and (-180 <= v <= 180):
        # Allow swapped detection only when clearly out of lat range but in lng range.
        if -180 <= v <= 180 and abs(v) > 90:
            return None
    return v


def _row_to_repeater(row: pd.Series, cols: dict[str, str]) -> dict | None:
    def get(field: str) -> str:
        col = cols.get(field)
        if not col:
            return ""
        return _clean_text(row.get(col))

    lat = _parse_coord(row.get(cols["latitude"])) if cols.get("latitude") else None
    lng = _parse_coord(row.get(cols["longitude"])) if cols.get("longitude") else None
    if lat is None or lng is None:
        return None
    if abs(lat) > 90 and abs(lng) <= 90:
        lat, lng = lng, lat
    if abs(lat) > 90 or abs(lng) > 180:
        return None

    refcode = get("refcode")
    repeater_number = get("repeater_number")
    serial_number = get("serial_number")
    repeater_id = serial_number or refcode or repeater_number
    if not repeater_id:
        repeater_id = f"rep-{lat:.5f}-{lng:.5f}"

    site_name = get("site_name") or get("neighborhood") or ""
    display_name = refcode or repeater_id
    repeater_type = get("repeater_type")
    technician = get("assign_to")
    contact_number = get("contact_number")

    return {
        "repeater_id": repeater_id,
        "refcode": refcode,
        "name": display_name,
        "site_name": site_name,
        "latitude": lat,
        "longitude": lng,
        "repeater_type": repeater_type,
        "supported_rats": supported_rats_from_type(repeater_type),
        "manufacturer": get("manufacturer"),
        "repeater_model": get("repeater_model"),
        "repeater_number": repeater_number,
        "status": get("status"),
        "remedy_action": get("remedy_action"),
        "neighborhood": get("neighborhood"),
        "address": get("address"),
        "category": get("category"),
        "subcategory": get("subcategory"),
        "outdoor_antenna": get("outdoor_antenna"),
        "serial_number": serial_number,
        "floor_no": get("floor_no"),
        "technician": technician,
        "assign_to": technician,
        "contact_number": contact_number,
        "requester": get("requester"),
        "customer_name_arabic": get("customer_name_arabic"),
        "technician_notes": get("technician_notes"),
        "solution_type": get("solution_type"),
        "submit_date": get("submit_date"),
        "source_type": "repeater",
    }


def load_all_repeaters(*, force_reload: bool = False) -> tuple[list[dict], str | None]:
    """
    Return (repeaters, source_path_or_error).
    Uses an in-memory cache keyed by file mtime.
    """
    raw_path = _find_latest_raw_repeater_file()
    if raw_path is None:
        dirs = ", ".join(str(d) for d in _REPEATER_DIRS)
        return [], f"No repeater spreadsheet found. Place a .xlsx or .csv file in: {dirs}"

    try:
        path = ensure_cleaned_repeater_sheet(raw_path)
    except Exception:
        path = raw_path

    mtime = path.stat().st_mtime
    raw_mtime = raw_path.stat().st_mtime
    cache_key = f"{raw_path}|{path}"
    if (
        not force_reload
        and _cache["path"] == cache_key
        and _cache["mtime"] == (mtime, raw_mtime)
        and _cache["rows"]
    ):
        return list(_cache["rows"]), str(path)

    df = _read_tabular(path)
    cols = _resolve_columns(df)
    if "latitude" not in cols or "longitude" not in cols:
        return [], f"Missing Latitude/Longitude columns in {path.name}"

    parsed: list[dict] = []
    for row_idx, series in df.iterrows():
        rec = _row_to_repeater(series, cols)
        if not rec:
            continue
        rec["_source_row"] = int(row_idx) if isinstance(row_idx, (int, float)) else len(parsed)
        parsed.append(rec)

    rows = _dedupe_repeater_rows(parsed)

    _cache["path"] = cache_key
    _cache["mtime"] = (mtime, raw_mtime)
    _cache["rows"] = rows
    return rows, str(path)


def repeater_matches_tech(repeater_type: str, tech: str | None) -> bool:
    if not tech or tech == "all":
        return True
    rt = re.sub(r"\s+", "", (repeater_type or "").lower())
    if not rt or rt == "non":
        return False
    t = tech.upper()
    if t == "2G":
        return "2g" in rt
    if t == "3G":
        return "3g" in rt
    if t in ("4G-FDD", "4G-TDD"):
        return "4g" in rt
    if t == "5G":
        return "5g" in rt
    return True


def repeaters_for_map(repeaters: list[dict]) -> list[dict]:
    """Lightweight rows for map pins (keeps API responses small)."""
    return [
        {
            "repeater_id": r["repeater_id"],
            "name": r.get("name") or r.get("refcode") or r["repeater_id"],
            "refcode": r.get("refcode") or r.get("name") or r["repeater_id"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "site_name": r.get("site_name") or "",
            "repeater_type": r.get("repeater_type") or "",
            "supported_rats": r.get("supported_rats") or "",
            "contact_number": r.get("contact_number") or "",
            "technician": r.get("technician") or r.get("assign_to") or "",
        }
        for r in repeaters
    ]


def filter_repeaters(
    repeaters: list[dict],
    *,
    tech: str = "",
    search: str = "",
    manufacturer: str = "",
    status: str = "",
    exclude_dismantled: bool = False,
) -> list[dict]:
    out: list[dict] = []
    term = (search or "").strip().lower()
    mfr = (manufacturer or "").strip().lower()
    st = (status or "").strip().lower()

    for r in repeaters:
        if tech and not repeater_matches_tech(r.get("repeater_type", ""), tech):
            continue
        if mfr and mfr != "all" and (r.get("manufacturer") or "").strip().lower() != mfr:
            continue
        if st and st != "all" and (r.get("status") or "").strip().lower() != st:
            continue
        if exclude_dismantled and "dismantle" in (r.get("remedy_action") or "").lower():
            continue
        if term:
            blob = " ".join(
                str(r.get(k) or "")
                for k in (
                    "repeater_id", "refcode", "serial_number", "site_name", "neighborhood",
                    "address", "repeater_number", "manufacturer",
                )
            ).lower()
            if term not in blob:
                continue
        out.append(r)
    return out
