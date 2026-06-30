"""
Step 2 loader:
Load raw tabular files from 5 paths into 5 databases (same treatment for cells and groups).

Mapping:
- raw/huawei/cells    -> huawei_pm_cells.db
- raw/huawei/groups   -> huawei_cell_groups.db
- raw/nokia/cells     -> nokia_pm_cells.db
- raw/nokia/groups    -> nokia_cell_groups.db
- raw/metadata/cells  -> metadata.db

Huawei/Nokia PM + groups (see sync_config):
  Prefer filtering by auto-detected date/time: rows strictly after MAX(time) in the table,
  then hash-dedupe (RAW_LOADER_TIME_FILTER). Fallback: hash-only incremental.
  Metadata snapshots still replace whole tables.

Supported: .csv, .txt, .tsv, .xlsx, .xlsm, .xls (Excel uses the first sheet only).
Nokia-style CSVs use semicolon; parsing matches ``sync.pm_processor`` (NetAct scoring).
"""

from __future__ import annotations

import hashlib
import argparse
import os
import warnings
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import (
    PROJECT_ROOT,
    HUAWEI_PM_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_PM_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_GROUPS_DAILY_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_GROUPS_DAILY_DB,
    METADATA_DB,
    DAILY_RETENTION_DAYS,
    PM_RETENTION_DAYS,
    RAW_LOADER_INCREMENTAL,
    RAW_LOADER_TIME_FILTER,
    RAW_LOADER_LATEST_ONLY,
    RAW_LOADER_DAILY_INCREMENTAL,
    RAW_DELETE_ALL_AFTER_LOAD,
    RAW_PRUNE_AFTER_LOAD,
    RAW_KEEP_FILES_PER_TECH,
)
from core.raw_pm_files import (  # noqa: E402
    clear_tabular_files,
    prune_stale_pm_files,
    relocate_legacy_all_folder,
    select_latest_files_per_technology,
)
from modules.sync.pm_processor import (
    _CELL_KEYWORDS,
    _detect_cell_identifier_column,
    _pick_best_timestamp_column,
    _read_nokia_csv_best,
)
from scripts.build_kpi_headers_db import build as build_kpi_headers_db
from pipeline.paths import PM_RATS, raw_path

HASH_COL = "_sync_row_hash"
HASH_LOOKUP_BATCH = 500


def _safe_table_name_from_file(file_name: str) -> str:
    stem = os.path.splitext(os.path.basename(file_name))[0].strip().lower()
    stem = re.sub(r"[^a-z0-9_]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    if not stem:
        stem = "table"
    if not stem[0].isalpha():
        stem = f"t_{stem}"
    return stem[:63]


def _infer_tech_from_file_name(file_name: str) -> str | None:
    low = _safe_table_name_from_file(file_name).lower()
    if re.search(r"(^|_)(5g|nr)($|_)", low):
        return "5G"
    if "4g_tdd" in low:
        return "4G"
    if "4g_fdd" in low:
        return "4G"
    if re.search(r"(^|_)(4g|lte)($|_)", low):
        return "4G"
    if re.search(r"(^|_)(3g|wcdma|umts)($|_)", low):
        return "3G"
    if re.search(r"(^|_)(2g|gsm)($|_)", low):
        return "2G"
    return None


def _infer_tech_from_columns(cols: list[str]) -> str | None:
    low = [str(c).strip().lower() for c in (cols or [])]
    joined = " ".join(low)
    if any(x in joined for x in ("nrcel", "gnb", "nr ")):
        return "5G"
    if any(x in joined for x in ("lncel", "enodeb", "eutran", "lte", "pci")):
        return "4G"
    if any(x in joined for x in ("wcel", "nodeb", "uarfcn", "psc")):
        return "3G"
    if any(x in joined for x in ("bts", "bcf", "gbsc", "cell ci", "bcc")):
        return "2G"
    return None


def _canonical_table_for_label(
    label: str,
    file_name: str,
    cols: list[str] | None = None,
    scope: str = "hourly",
) -> str | None:
    tech = _infer_tech_from_file_name(file_name) or _infer_tech_from_columns(cols or [])
    if not tech:
        return None
    scope_tag = "DAILY" if str(scope).lower() == "daily" else "HOURLY"
    if label.endswith("-cells"):
        return f"{tech}_CELLS_{scope_tag}"
    if label.endswith("-groups"):
        return f"{tech}_GROUPS_{scope_tag}"
    return None


def _drop_non_canonical_tables(conn: sqlite3.Connection, label: str, scope: str = "hourly") -> None:
    keep: set[str] = set()
    scope_tag = "DAILY" if str(scope).lower() == "daily" else "HOURLY"
    if label.endswith("-cells"):
        keep = {f"{t}_CELLS_{scope_tag}" for t in ("2G", "3G", "4G", "5G")}
    elif label.endswith("-groups"):
        keep = {f"{t}_GROUPS_{scope_tag}" for t in ("2G", "3G", "4G", "5G")}
        # Keep app-managed schema tables if present.
        keep.update({"groups", "group_cells"})
    if not keep:
        return
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (name,) in rows:
        if name in keep:
            continue
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        print(f"[{label}] dropped non-canonical table: {name}")


_TABULAR_EXTS = (".csv", ".txt", ".tsv", ".xlsx", ".xlsm", ".xls")
CSV_CHUNK_SIZE = 50000

# Huawei/Nokia exports may append " DST" / " STD"; pandas treats them as TZ tokens.
_PSEUDO_TZ_SUFFIX_RE = re.compile(r"\s+(DST|STD)\s*$", re.IGNORECASE)


def _sanitize_timestamp_strings(vals: pd.Series) -> pd.Series:
    return vals.str.replace(_PSEUDO_TZ_SUFFIX_RE, "", regex=True).str.strip()


def _parse_datetime_fallback(vals: pd.Series, *, prefer_dayfirst: bool = True) -> pd.Series:
    """Last-resort parse without dayfirst/format inference warnings."""
    out = pd.Series(pd.NaT, index=vals.index, dtype="datetime64[ns]")

    compact = vals.str.replace(r"\.0+$", "", regex=True)
    for length, fmt in (
        (8, "%Y%m%d"),
        (10, "%Y%m%d%H"),
        (12, "%Y%m%d%H%M"),
        (14, "%Y%m%d%H%M%S"),
    ):
        mask = compact.str.len() == length
        if not mask.any():
            continue
        out.loc[mask] = pd.to_datetime(compact.loc[mask], format=fmt, errors="coerce")

    remaining_idx = out.index[out.isna()]
    if len(remaining_idx) == 0:
        return out

    remaining = vals.loc[remaining_idx]
    dotted = remaining.str.contains(r"\.", na=False)
    slashed = remaining.str.contains(r"/", na=False)

    if prefer_dayfirst:
        if dotted.any():
            dot_idx = remaining.index[dotted]
            for fmt in (
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y",
                "%m.%d.%Y %H:%M:%S",
                "%m.%d.%Y %H:%M",
                "%m.%d.%Y",
            ):
                unparsed = dot_idx[out.loc[dot_idx].isna()]
                if len(unparsed) == 0:
                    break
                parsed = pd.to_datetime(remaining.loc[unparsed], format=fmt, errors="coerce")
                out.loc[parsed.index[parsed.notna()]] = parsed.loc[parsed.notna()]

        if slashed.any():
            unparsed = remaining.index[slashed & out.loc[remaining.index].isna()]
            if len(unparsed):
                parsed = pd.to_datetime(remaining.loc[unparsed], errors="coerce", dayfirst=True)
                na_idx = parsed.index[parsed.isna()]
                if len(na_idx):
                    parsed.loc[na_idx] = pd.to_datetime(
                        remaining.loc[na_idx], errors="coerce", dayfirst=False
                    )
                out.loc[unparsed] = parsed

        still_na = out.index[out.isna()]
        if len(still_na):
            out.loc[still_na] = pd.to_datetime(
                vals.loc[still_na], errors="coerce", dayfirst=False
            )
    else:
        if dotted.any():
            dot_idx = remaining.index[dotted]
            for fmt in (
                "%m.%d.%Y %H:%M:%S",
                "%m.%d.%Y %H:%M",
                "%m.%d.%Y",
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y",
            ):
                unparsed = dot_idx[out.loc[dot_idx].isna()]
                if len(unparsed) == 0:
                    break
                parsed = pd.to_datetime(remaining.loc[unparsed], format=fmt, errors="coerce")
                out.loc[parsed.index[parsed.notna()]] = parsed.loc[parsed.notna()]

        parsed = pd.to_datetime(remaining, errors="coerce", dayfirst=False)
        na_idx = parsed.index[parsed.isna()]
        if len(na_idx):
            retry_mask = slashed.loc[na_idx]
            if retry_mask.any():
                retry_idx = na_idx[retry_mask]
                parsed.loc[retry_idx] = pd.to_datetime(
                    remaining.loc[retry_idx], errors="coerce", dayfirst=True
                )
        out.loc[remaining_idx] = parsed

    return out


def _parse_timestamp_series(series: pd.Series, label: str, col_name: str) -> pd.Series:
    col = str(col_name or "").strip().lower()
    vals = _sanitize_timestamp_strings(series.astype(str).str.strip())

    def _parse_with_formats_fill(formats: tuple[str, ...]) -> pd.Series | None:
        out = pd.Series(pd.NaT, index=vals.index, dtype="datetime64[ns]")
        for fmt in formats:
            ts = pd.to_datetime(vals, format=fmt, errors="coerce")
            mask = out.isna() & ts.notna()
            if mask.any():
                out.loc[mask] = ts.loc[mask]
        return out if out.notna().any() else None

    # Huawei PM/groups daily/hourly exports can be either:
    # - DD/MM/YY HH:MM
    # - DD/MM/YYYY HH:MM
    # - DD/MM/YYYY
    if label.startswith("huawei-") and col in ("time", "date"):
        ts = _parse_with_formats_fill((
            "%d/%m/%y %H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%d/%m/%y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ))
        if ts is not None:
            return ts
        return _parse_datetime_fallback(vals, prefer_dayfirst=True)

    # Nokia PM/groups daily/hourly exports can be either:
    # - MM.DD.YY HH:MM:SS (hourly)
    # - DD.MM.YYYY / DD.MM.YYYY HH:MM:SS (daily variants)
    if label.startswith("nokia-") and col in ("period_start_time", "time", "date"):
        ts = _parse_with_formats_fill((
            "%m.%d.%y %H:%M:%S",
            "%m.%d.%Y %H:%M:%S",
            "%m.%d.%Y %H:%M",
            "%m.%d.%Y",
            "%m.%d.%y",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y",
            "%d.%m.%y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ))
        if ts is not None:
            return ts
        return _parse_datetime_fallback(vals, prefer_dayfirst=False)

    return _parse_datetime_fallback(vals, prefer_dayfirst=True)


def _parse_single_timestamp(raw_val, label: str, col_name: str) -> pd.Timestamp | None:
    if raw_val is None:
        return None
    s = str(raw_val).strip()
    if s in ("", "None", "NaT"):
        return None
    ts = _parse_timestamp_series(pd.Series([s]), label, col_name).iloc[0]
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _detect_huawei_header_row(path: str) -> int:
    """Find Huawei CSV header row where first cell is 'Time' or 'Date'."""
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="ignore") as fh:
                for i in range(200):
                    line = fh.readline()
                    if line == "":
                        break
                    parts = [p.strip().strip('"').strip("'") for p in line.rstrip("\r\n").split(",")]
                    first_cell = (parts[0] if parts else "").strip().lower()
                    if first_cell in ("time", "date"):
                        return i
        except Exception:
            continue
    return 0


def _csv_chunk_iter(path: str, label: str, chunksize: int = CSV_CHUNK_SIZE):
    """Yield CSV chunks with vendor-specific parsing."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".csv", ".txt", ".tsv"):
        raise ValueError("chunk iterator supports csv/txt/tsv only")
    if label.startswith("nokia-"):
        # Nokia exports are semicolon-delimited.
        return pd.read_csv(
            path,
            sep=";",
            encoding="latin-1",
            engine="python",
            on_bad_lines="skip",
            chunksize=chunksize,
        )
    if label.startswith("huawei-"):
        # Huawei cells often have preamble rows before the real header.
        skiprows = _detect_huawei_header_row(path) if label == "huawei-cells" else 0
        return pd.read_csv(
            path,
            sep=",",
            encoding="utf-8-sig",
            engine="python",
            on_bad_lines="skip",
            skiprows=skiprows,
            chunksize=chunksize,
        )
    return pd.read_csv(
        path,
        sep=None,
        encoding="latin-1",
        engine="python",
        on_bad_lines="skip",
        chunksize=chunksize,
    )


def _resolve_cell_time_key_columns(
    db_cols: list[str],
    sample: pd.DataFrame,
) -> tuple[str | None, str | None]:
    """Vendor-native (cell name, period start) columns for dedupe."""
    cell_det = _detect_cell_identifier_column(db_cols, _CELL_KEYWORDS)
    cell_col = _match_column_name(db_cols, cell_det)
    ts_det = _pick_best_timestamp_column(sample, list(sample.columns))
    ts_col = _match_column_name(db_cols, ts_det)
    return cell_col, ts_col


def _dedupe_table_on_cell_time(
    conn: sqlite3.Connection,
    table: str,
    cell_col: str,
    ts_col: str,
) -> int:
    """Keep one row per (cell, time); return number of rows removed."""
    before = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    conn.execute(
        f'DELETE FROM "{table}" WHERE rowid NOT IN ('
        f'  SELECT MIN(rowid) FROM "{table}"'
        f'  GROUP BY "{cell_col}", "{ts_col}"'
        f')'
    )
    after = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    return max(0, before - after)


def _load_csv_file_incremental_in_chunks(
    conn: sqlite3.Connection,
    table: str,
    full_path: str,
    label: str,
    fn: str,
) -> None:
    it = _csv_chunk_iter(full_path, label, chunksize=CSV_CHUNK_SIZE)
    table_exists = _table_exists(conn, table)
    table_existed_at_start = table_exists
    db_cols: list[str] | None = None
    ts_col: str | None = None
    max_ts: pd.Timestamp | None = None
    total_rows = 0
    inserted_rows = 0
    chunk_count = 0
    first_sample: pd.DataFrame | None = None

    for chunk in it:
        if chunk is None or chunk.empty:
            continue
        chunk_count += 1
        if first_sample is None:
            first_sample = chunk
        total_rows += len(chunk)

        if not table_exists:
            # First insert creates table shape; no time filter needed for fresh table.
            chunk.to_sql(table, conn, if_exists="append", index=False)
            inserted_rows += len(chunk)
            table_exists = True
            db_cols = list(chunk.columns)
            continue

        if db_cols is None:
            raw_db_cols = _pragma_column_names(conn, table)
            db_cols = [c for c in raw_db_cols if c != HASH_COL]
            if set(db_cols) != set(chunk.columns):
                before_cols = len(db_cols)
                db_cols = _ensure_table_columns(conn, table, db_cols, list(chunk.columns))
                print(
                    f"[{label}] incremental {fn} -> table {table}: "
                    f"columns changed, evolved schema ({before_cols}->{len(db_cols)} columns)"
                )

        aligned = chunk.reindex(columns=db_cols)
        work = aligned
        if RAW_LOADER_TIME_FILTER:
            if ts_col is None:
                det = _pick_best_timestamp_column(chunk, list(chunk.columns))
                ts_col = _match_column_name(db_cols, det)
                if ts_col is not None and max_ts is None:
                    max_ts = _max_ts_in_column(conn, table, ts_col, label)
            if ts_col is not None and max_ts is not None and pd.notna(max_ts):
                ts_vals = _parse_timestamp_series(aligned[ts_col], label, ts_col)
                work = aligned.loc[(ts_vals > max_ts) & ts_vals.notna()].copy()

        if work.empty:
            continue
        work.to_sql(table, conn, if_exists="append", index=False)
        inserted_rows += len(work)
        if RAW_LOADER_TIME_FILTER and ts_col is not None:
            ts_vals = _parse_timestamp_series(aligned[ts_col], label, ts_col)
            chunk_max = ts_vals.max()
            if pd.notna(chunk_max):
                chunk_max = pd.Timestamp(chunk_max)
                if max_ts is None or pd.isna(max_ts) or chunk_max > max_ts:
                    max_ts = chunk_max

    dedupe_note = ""
    if (
        RAW_LOADER_TIME_FILTER
        and table_existed_at_start
        and chunk_count > 1
        and db_cols
        and first_sample is not None
    ):
        cell_col, ts_col = _resolve_cell_time_key_columns(db_cols, first_sample)
        if cell_col and ts_col:
            removed = _dedupe_table_on_cell_time(conn, table, cell_col, ts_col)
            if removed:
                dedupe_note = f", deduped {removed} rows on ({cell_col}, {ts_col})"

    print(
        f"[{label}] incremental {fn} -> table {table}: "
        f"+{inserted_rows} rows (file {total_rows} rows, chunked{dedupe_note})"
    )


def _read_huawei_csv_best(path: str) -> pd.DataFrame | None:
    """
    Huawei exports often have a preamble (blank lines, 'GUL Daily', 'Save Time', 'User Name')
    before the actual CSV header. Detect the true header row and parse from there.

    Hourly workbooks normalized to CSV usually start the header with **Time**; **daily**
    PRS exports often use **Date** as the first column — same rule as ``_detect_huawei_header_row``.
    """
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="ignore") as fh:
                lines = []
                for _ in range(120):
                    line = fh.readline()
                    if line == "":
                        break
                    lines.append(line.rstrip("\r\n"))
        except Exception:
            continue
        header_idx = None
        for i, line in enumerate(lines):
            parts = [p.strip().strip('"').strip("'") for p in line.split(",")]
            first_cell = (parts[0] if parts else "").strip().lower()
            # True table header: first cell Time or Date, and enough commas for cell + KPI columns.
            if first_cell in ("time", "date") and line.count(",") >= 3:
                header_idx = i
                break
        if header_idx is None:
            continue
        try:
            df = pd.read_csv(
                path,
                sep=",",
                skiprows=header_idx,
                encoding=enc,
                engine="python",
                on_bad_lines="skip",
            )
            # Keep only meaningful columns and rows.
            df = df.dropna(axis=1, how="all")
            if not df.empty and len(df.columns) >= 3:
                return df
        except Exception:
            continue
    return None


def _read_csv_auto(path: str) -> pd.DataFrame:
    """
    Nokia / NetAct CSVs (including group KPI exports) are usually ``;``-separated.
    Using comma or bad sniffs yields one column whose *name* is several headers joined by ``;``.
    Reuse ``_read_nokia_csv_best`` (encoding × delimiter + parse score), then generic fallback.
    """
    huawei_df = _read_huawei_csv_best(path)
    if huawei_df is not None and len(huawei_df.columns) >= 3:
        return huawei_df
    nokia_df = _read_nokia_csv_best(path)
    if nokia_df is not None and len(nokia_df.columns) >= 2:
        return nokia_df
    try:
        return pd.read_csv(path, sep=None, engine="python")
    except Exception:
        pass
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        for sep in (',', ';', '\t', '|'):
            try:
                return pd.read_csv(
                    path,
                    sep=sep,
                    encoding=enc,
                    engine='python',
                    on_bad_lines='skip',
                )
            except Exception:
                continue
    return pd.read_csv(path, sep=None, engine="python", encoding='latin-1', on_bad_lines='skip')


def _read_tabular_as_is(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt", ".tsv"):
        return _read_csv_auto(path)
    if ext in (".xlsx", ".xlsm"):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Workbook contains no default style, apply openpyxl's default",
                category=UserWarning,
            )
            return pd.read_excel(path, sheet_name=0, engine="openpyxl")
    if ext == ".xls":
        return pd.read_excel(path, sheet_name=0)
    raise ValueError(f"unsupported extension: {ext}")


def _stable_row_hashes(df: pd.DataFrame) -> pd.Series:
    """Deterministic row digest (sorted column names, UTF-8)."""
    if df.empty:
        return pd.Series(dtype=object)
    cols = sorted(df.columns)
    sub = df[cols]
    combined = sub.astype(str, copy=False).agg('|'.join, axis=1)
    return combined.map(
        lambda s: hashlib.sha256(s.encode('utf-8', errors='replace')).hexdigest()
    )


def _prepare_hashed_frame(df_raw: pd.DataFrame) -> pd.DataFrame:
    if df_raw.empty:
        return df_raw.copy()
    out = df_raw.copy()
    out[HASH_COL] = _stable_row_hashes(out)
    return out.drop_duplicates(subset=[HASH_COL], keep='first')


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _pragma_column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _sqlite_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ensure_table_columns(
    conn: sqlite3.Connection,
    table: str,
    existing_cols: list[str],
    incoming_cols: list[str],
) -> list[str]:
    """Add new incoming columns without replacing retained PM history."""
    cols = list(existing_cols)
    seen = {str(c).lower().strip() for c in cols}
    for col in incoming_cols:
        key = str(col).lower().strip()
        if not key or key in seen:
            continue
        conn.execute(f'ALTER TABLE {_sqlite_ident(table)} ADD COLUMN {_sqlite_ident(col)} TEXT')
        cols.append(col)
        seen.add(key)
    return cols


def _ensure_hash_index(conn: sqlite3.Connection, table: str) -> None:
    """Speed up duplicate checks when tables grow large."""
    idx = re.sub(r"[^a-z0-9_]+", "_", f"idx_{table}_{HASH_COL}")[:56]
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{table}" ("{HASH_COL}")'
    )


def _match_column_name(data_cols: list[str], detected: str | None) -> str | None:
    if not detected:
        return None
    if detected in data_cols:
        return detected
    dl = str(detected).lower().strip()
    for c in data_cols:
        if str(c).lower().strip() == dl:
            return c
    return None


def _max_ts_in_column(
    conn: sqlite3.Connection, table: str, col: str, label: str
) -> pd.Timestamp | None:
    """Latest parsed timestamp in ``col`` (never trust lexicographic SQL MAX on text)."""
    try:
        n = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return None
    if n == 0:
        return None
    best = pd.NaT
    try:
        for chunk in pd.read_sql_query(
            f'SELECT "{col}" AS v FROM "{table}"', conn, chunksize=65536
        ):
            ts = _parse_timestamp_series(chunk["v"], label, col)
            m = ts.max()
            if pd.notna(m) and (pd.isna(best) or m > best):
                best = m
    except Exception:
        return None
    if pd.isna(best):
        return None
    return pd.Timestamp(best)


def _hashes_already_present(conn: sqlite3.Connection, table: str, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    present: set[str] = set()
    for i in range(0, len(hashes), HASH_LOOKUP_BATCH):
        batch = hashes[i : i + HASH_LOOKUP_BATCH]
        ph = ','.join('?' * len(batch))
        rows = conn.execute(
            f'SELECT "{HASH_COL}" FROM "{table}" WHERE "{HASH_COL}" IN ({ph})',
            batch,
        ).fetchall()
        present.update(str(r[0]) for r in rows if r[0] is not None)
    return present


def _load_file_incremental(
    conn: sqlite3.Connection,
    table: str,
    df_raw: pd.DataFrame,
    label: str,
    fn: str,
) -> None:
    if df_raw.empty:
        print(f"[{label}] incremental {fn} -> table {table}: skip (empty)")
        return

    if not _table_exists(conn, table):
        if df_raw.empty:
            print(f"[{label}] incremental {fn} -> table {table}: skip (empty)")
            return
        df_raw.to_sql(table, conn, if_exists='append', index=False)
        print(f"[{label}] incremental {fn} -> table {table}: created ({len(df_raw)} rows)")
        return

    db_cols = _pragma_column_names(conn, table)
    # Backward compatibility: legacy tables may still have old hash column.
    data_cols = [c for c in db_cols if c != HASH_COL]
    incoming_cols = list(df_raw.columns)
    if set(data_cols) != set(incoming_cols):
        if df_raw.empty:
            print(f"[{label}] incremental {fn} -> table {table}: skip (empty)")
            return
        before_cols = len(data_cols)
        data_cols = _ensure_table_columns(conn, table, data_cols, incoming_cols)
        print(
            f"[{label}] incremental {fn} -> table {table}: "
            f"columns changed, evolved schema ({before_cols}->{len(data_cols)} columns)"
        )

    aligned = df_raw.reindex(columns=data_cols)
    work = aligned
    time_note = ''

    if RAW_LOADER_TIME_FILTER:
        ts_col = _pick_best_timestamp_column(df_raw, list(df_raw.columns))
        db_ts = _match_column_name(data_cols, ts_col)
        if ts_col is not None and db_ts is not None:
            max_ts = _max_ts_in_column(conn, table, db_ts, label)
            ts_vals = _parse_timestamp_series(aligned[db_ts], label, db_ts)
            if max_ts is not None and pd.notna(max_ts):
                mask = (ts_vals > max_ts) & ts_vals.notna()
                time_note = f"time>{max_ts}"
            else:
                mask = ts_vals.notna()
                time_note = 'time filter (no prior MAX, all rows with valid times)'
            work = aligned.loc[mask].copy()
            if work.empty:
                print(
                    f"[{label}] incremental {fn} -> table {table}: "
                    f"+0 rows after time filter ({time_note}, file {len(df_raw)} rows)"
                )
                return

    if work.empty:
        print(
            f"[{label}] incremental {fn} -> table {table}: "
            f"+0 rows after time filter (file {len(df_raw)} rows)"
        )
        return

    # No hash-based dedupe: rows are assumed unique by (cell, time) in source.
    work.to_sql(table, conn, if_exists='append', index=False)
    extra = f' [{time_note}]' if time_note else ''
    print(
        f"[{label}] incremental {fn} -> table {table}: "
        f"+{len(work)} rows (file {len(df_raw)} rows, after filter {len(work)}{extra})"
    )


def _metadata_canonical_table(table: str) -> str | None:
    low = (table or "").lower()
    if "4g_tdd" in low:
        return "cells_4g_tdd"
    if "4g_fdd" in low:
        return "cells_4g_fdd"
    if re.search(r"(^|_)5g($|_)", low):
        return "cells_5g"
    if re.search(r"(^|_)3g($|_)", low):
        return "cells_3g"
    if re.search(r"(^|_)2g($|_)", low):
        return "cells_2g"
    return None


def _metadata_canonical_table_from_file_name(file_name: str) -> str | None:
    low = _safe_table_name_from_file(file_name).lower()
    if "4g_tdd" in low:
        return "cells_4g_tdd"
    if "4g_fdd" in low:
        return "cells_4g_fdd"
    if re.search(r"(^|_)5g($|_)", low):
        return "cells_5g"
    if re.search(r"(^|_)3g($|_)", low):
        return "cells_3g"
    if re.search(r"(^|_)2g($|_)", low):
        return "cells_2g"
    return None


_METADATA_TECH_FOR_CANONICAL: dict[str, str] = {
    "cells_2g": "2G",
    "cells_3g": "3G",
    "cells_4g_fdd": "4G-FDD",
    "cells_4g_tdd": "4G-TDD",
    "cells_5g": "5G",
}


def _mirror_metadata_table_for_map(conn: sqlite3.Connection, source_table: str, df: pd.DataFrame) -> None:
    """
    Keep compatibility for map/performance routes that read canonical metadata tables.
    Raw table (`t_*`) remains as-is; this mirrors the same data to cells_2g/... tables.
    """
    canonical = _metadata_canonical_table(source_table)
    if not canonical:
        return
    mirrored = df.copy()
    mirrored.columns = [str(c).strip().lower() for c in mirrored.columns]
    mirrored.to_sql(canonical, conn, if_exists="replace", index=False)
    print(f"[metadata] mirrored {source_table} -> {canonical} ({len(mirrored)} rows)")


def _cleanup_legacy_metadata_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 't_%'"
    ).fetchall()
    for (name,) in rows:
        canonical = _metadata_canonical_table(name)
        if canonical:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            print(f"[metadata] dropped legacy table {name}")


def _rebuild_sites_from_metadata(conn: sqlite3.Connection) -> None:
    """
    Rebuild `sites` from canonical metadata tech tables so Network Map joins work.
    """
    conn.execute("DELETE FROM sites")
    union_sql = """
        SELECT CAST(site_id AS TEXT) AS site_id, site_name, lat, "long", vendor FROM cells_2g
        UNION ALL
        SELECT CAST(nodeb_id AS TEXT) AS site_id, nodeb_name AS site_name, lat, "long", vendor FROM cells_3g
        UNION ALL
        SELECT CAST(enb_id_actual AS TEXT) AS site_id, enb_name AS site_name, lat, "long", vendor FROM cells_4g_fdd
        UNION ALL
        SELECT CAST(enb_id_actual AS TEXT) AS site_id, enb_name AS site_name, lat, "long", vendor FROM cells_4g_tdd
        UNION ALL
        SELECT CAST(gnb_id_actual AS TEXT) AS site_id, gnb_name AS site_name, lat, "long", vendor FROM cells_5g
    """
    conn.execute(
        f"""
        INSERT INTO sites (site_id, site_name, latitude, longitude, vendor, status)
        SELECT
            site_id,
            COALESCE(MAX(NULLIF(TRIM(site_name), '')), site_id) AS site_name,
            MAX(CAST(lat AS REAL)) AS latitude,
            MAX(CAST("long" AS REAL)) AS longitude,
            MAX(vendor) AS vendor,
            'Active' AS status
        FROM ({union_sql}) u
        WHERE site_id IS NOT NULL AND TRIM(site_id) <> ''
        GROUP BY site_id
        """
    )
    print("[metadata] rebuilt sites table from canonical per-tech metadata tables")


def _load_folder_tabular_to_db(
    folder: str,
    db_path: str,
    label: str,
    *,
    incremental: bool,
    scope: str = "hourly",
) -> tuple[int, int]:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if not os.path.isdir(folder):
        print(f"[{label}] folder not found: {folder}")
        return 0, 0

    all_files = [
        f
        for f in os.listdir(folder)
        if f.lower().endswith(_TABULAR_EXTS) and not f.startswith("~$")
    ]
    if not all_files:
        print(f"[{label}] no tabular files ({', '.join(_TABULAR_EXTS)}) in {folder}")
        return 0, 0

    files = list(all_files)
    if (
        incremental
        and RAW_LOADER_LATEST_ONLY
        and label in ("huawei-cells", "nokia-cells", "huawei-groups", "nokia-groups")
    ):
        files = select_latest_files_per_technology(folder, files)
        skipped = len(all_files) - len(files)
        if skipped:
            print(
                f"[{label}] latest-only: loading {len(files)} file(s), "
                f"skipping {skipped} older export(s) in {folder}"
            )
    files.sort()
    loaded = 0
    failed = 0
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        for fn in files:
            full_path = os.path.join(folder, fn)
            try:
                ext = os.path.splitext(fn)[1].lower()
                use_chunked = (
                    incremental
                    and label in ("huawei-cells", "nokia-cells")
                    and ext in (".csv", ".txt", ".tsv")
                )
                if use_chunked:
                    table = _canonical_table_for_label(label, fn, scope=scope)
                    if not table:
                        print(f"[{label}] skipped {fn}: could not infer technology for canonical table")
                        failed += 1
                        continue
                    _load_csv_file_incremental_in_chunks(conn, table, full_path, label, fn)
                else:
                    df = _read_tabular_as_is(full_path)
                    table = _canonical_table_for_label(label, fn, list(df.columns), scope=scope)
                    if label != "metadata" and not table:
                        print(f"[{label}] skipped {fn}: could not infer technology for canonical table")
                        failed += 1
                        continue
                    if incremental:
                        _load_file_incremental(conn, table, df, label, fn)
                    else:
                        if label == "metadata":
                            canonical = _metadata_canonical_table_from_file_name(fn)
                            if not canonical:
                                print(f"[metadata] skipped {fn}: could not map to canonical cells_* table")
                                continue
                            out = df.copy()
                            out.columns = [str(c).strip().lower() for c in out.columns]
                            out.to_sql(canonical, conn, if_exists="replace", index=False)
                            print(f"[metadata] replaced {fn} -> table {canonical} ({len(out)} rows)")
                        else:
                            df.to_sql(table, conn, if_exists="replace", index=False)
                            print(f"[{label}] replaced {fn} -> table {table} ({len(df)} rows)")
                loaded += 1
            except Exception as e:
                print(f"[{label}] failed {fn}: {e}")
                failed += 1
        if label == "metadata":
            try:
                _cleanup_legacy_metadata_tables(conn)
                _rebuild_sites_from_metadata(conn)
            except Exception as ex:
                print(f"[metadata] failed rebuilding sites table: {ex}")
                failed += 1
        else:
            try:
                _drop_non_canonical_tables(conn, label, scope=scope)
            except Exception as ex:
                print(f"[{label}] canonical cleanup warning: {ex}")
        conn.commit()
        if loaded > 0 and label in ("huawei-cells", "nokia-cells", "huawei-groups", "nokia-groups"):
            if RAW_DELETE_ALL_AFTER_LOAD:
                removed = clear_tabular_files(folder)
                if removed:
                    print(f"[{label}] deleted {removed} raw file(s) after load: {folder}")
            elif incremental and RAW_PRUNE_AFTER_LOAD:
                removed = prune_stale_pm_files(
                    folder, keep_per_technology=RAW_KEEP_FILES_PER_TECH
                )
                if removed:
                    print(f"[{label}] pruned {removed} older raw file(s) from {folder}")
    finally:
        conn.close()
    return loaded, failed


def _incremental_for_label(label: str, scope: str = "hourly") -> bool:
    if label == "metadata":
        return False
    if str(scope).lower() == "daily":
        return RAW_LOADER_DAILY_INCREMENTAL and RAW_LOADER_INCREMENTAL
    return RAW_LOADER_INCREMENTAL


def _parse_args():
    parser = argparse.ArgumentParser(description="Load raw tabular files into local databases")
    parser.add_argument(
        "--scope",
        choices=("hourly", "daily"),
        default="hourly",
        help="Dataset scope to load (default: hourly)",
    )
    parser.add_argument(
        "--skip-kpi-db",
        action="store_true",
        help="Skip KPI headers DB rebuild",
    )
    parser.add_argument(
        "--category",
        choices=("all", "cells", "groups", "metadata"),
        default="all",
        help="Limit loading category (default: all)",
    )
    parser.add_argument(
        "--vendor",
        choices=("all", "nokia", "huawei"),
        default="all",
        help="Limit to one vendor's PM/group folders (default: all)",
    )
    return parser.parse_args()


def _apply_daily_retention_to_db(db_path: str, days: int, label: str) -> None:
    from core.pm_retention import apply_retention

    apply_retention(db_path, days, label)


def _relocate_legacy_all_inputs(scope: str, vendor: str, category: str) -> None:
    """Make the loader tolerant of raw files left in legacy ``.../all/<scope>`` staging."""
    if category == "metadata":
        return
    vendors = ("huawei", "nokia") if vendor == "all" else (vendor,)
    domains = ("cells", "groups") if category == "all" else (category,)
    for v in vendors:
        for domain in domains:
            moved = relocate_legacy_all_folder(v, domain, scope)
            if moved:
                print(f"[{v}-{domain}] relocated {moved} file(s) from legacy .../all/{scope} before load")


def main() -> int:
    args = _parse_args()
    scope = args.scope
    is_daily = scope == "daily"
    _relocate_legacy_all_inputs(scope, args.vendor, args.category)

    mappings: list[tuple[str, str, str]] = []
    for tech in PM_RATS:
        mappings.append(
            (
                raw_path("huawei", "cells", tech, scope),
                HUAWEI_PM_DAILY_DB if is_daily else HUAWEI_PM_DB,
                "huawei-cells",
            )
        )
        mappings.append(
            (
                raw_path("huawei", "groups", tech, scope),
                HUAWEI_GROUPS_DAILY_DB if is_daily else HUAWEI_GROUPS_DB,
                "huawei-groups",
            )
        )
        mappings.append(
            (
                raw_path("nokia", "cells", tech, scope),
                NOKIA_PM_DAILY_DB if is_daily else NOKIA_PM_DB,
                "nokia-cells",
            )
        )
        mappings.append(
            (
                raw_path("nokia", "groups", tech, scope),
                NOKIA_GROUPS_DAILY_DB if is_daily else NOKIA_GROUPS_DB,
                "nokia-groups",
            )
        )
    if not is_daily:
        mappings.append((raw_path("metadata", "cells", "all", "snapshot"), METADATA_DB, "metadata"))

    if args.category != "all":
        if args.category == "metadata":
            mappings = [m for m in mappings if m[2] == "metadata"]
        else:
            needle = f"-{args.category}"
            mappings = [m for m in mappings if needle in m[2]]

    if args.vendor != "all":
        mappings = [m for m in mappings if m[2].startswith(f"{args.vendor}-")]

    total_loaded = 0
    total_failed = 0
    with ThreadPoolExecutor(max_workers=len(mappings)) as pool:
        futures = {
            pool.submit(
                _load_folder_tabular_to_db,
                folder,
                db,
                label,
                incremental=_incremental_for_label(label, scope),
                scope=scope,
            ): label
            for folder, db, label in mappings
        }
        for fut in as_completed(futures):
            loaded, failed = fut.result()
            total_loaded += loaded
            total_failed += failed

    mode = 'incremental_pm_groups+replace_metadata' if RAW_LOADER_INCREMENTAL else 'replace_all'
    mode = f'{mode}:{scope}'
    if RAW_LOADER_INCREMENTAL and RAW_LOADER_TIME_FILTER:
        mode += '+time_before_hash'
    elif RAW_LOADER_INCREMENTAL:
        mode += '+hash_only'
    if not args.skip_kpi_db:
        try:
            detailed, scoped = build_kpi_headers_db()
            print(f"[kpi-db] refreshed detailed_rows={detailed} scope_rows={scoped}")
        except Exception as ex:
            print(f"[kpi-db] refresh failed: {ex}")
            total_failed += 1

    if is_daily:
        _apply_daily_retention_to_db(NOKIA_PM_DAILY_DB, DAILY_RETENTION_DAYS, "daily-retention-nokia-cells")
        _apply_daily_retention_to_db(HUAWEI_PM_DAILY_DB, DAILY_RETENTION_DAYS, "daily-retention-huawei-cells")
        _apply_daily_retention_to_db(NOKIA_GROUPS_DAILY_DB, DAILY_RETENTION_DAYS, "daily-retention-nokia-groups")
        _apply_daily_retention_to_db(HUAWEI_GROUPS_DAILY_DB, DAILY_RETENTION_DAYS, "daily-retention-huawei-groups")
    elif PM_RETENTION_DAYS > 0:
        # Hourly Nokia/Huawei PM + groups: keep last PM_RETENTION_DAYS (default 7) calendar days in DB.
        if args.category in ("all", "cells"):
            _apply_daily_retention_to_db(NOKIA_PM_DB, PM_RETENTION_DAYS, "hourly-retention-nokia-cells")
            _apply_daily_retention_to_db(HUAWEI_PM_DB, PM_RETENTION_DAYS, "hourly-retention-huawei-cells")
        if args.category in ("all", "groups"):
            _apply_daily_retention_to_db(NOKIA_GROUPS_DB, PM_RETENTION_DAYS, "hourly-retention-nokia-groups")
            _apply_daily_retention_to_db(HUAWEI_GROUPS_DB, PM_RETENTION_DAYS, "hourly-retention-huawei-groups")

    if args.category in ("all", "cells", "groups"):
        try:
            from core.pm_indexes import ensure_all_pm_databases

            index_categories = (
                ("cells", "groups")
                if args.category == "all"
                else (args.category,)
            )
            index_payload = ensure_all_pm_databases(
                scope=scope,
                categories=index_categories,
            )
            for line in index_payload.get("messages") or []:
                print(line)
        except Exception as ex:
            print(f"[pm-indexes] warning: {ex}")

    print(f"[done] mode={mode} loaded_tables={total_loaded} failed_files={total_failed}")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
