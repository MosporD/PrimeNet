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
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
)
from sync.pm_processor import _pick_best_timestamp_column, _read_nokia_csv_best
from scripts.build_kpi_headers_db import build as build_kpi_headers_db

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


def _parse_timestamp_series(series: pd.Series, label: str, col_name: str) -> pd.Series:
    col = str(col_name or "").strip().lower()
    vals = series.astype(str).str.strip()

    # Huawei PM/groups daily/hourly exports can be either:
    # - DD/MM/YY HH:MM
    # - DD/MM/YYYY HH:MM
    # - DD/MM/YYYY
    if label.startswith("huawei-") and col in ("time", "date"):
        for fmt in (
            "%d/%m/%y %H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%d/%m/%y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            ts = pd.to_datetime(vals, format=fmt, errors="coerce")
            if ts.notna().any():
                return ts
        return pd.to_datetime(vals, errors="coerce", dayfirst=True)

    # Nokia PM/groups daily/hourly exports can be either:
    # - MM.DD.YY HH:MM:SS (hourly)
    # - DD.MM.YYYY / DD.MM.YYYY HH:MM:SS (daily variants)
    if label.startswith("nokia-") and col in ("period_start_time", "time", "date"):
        for fmt in (
            "%m.%d.%y %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y",
            "%d.%m.%y",
            "%m.%d.%Y %H:%M:%S",
            "%m.%d.%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            ts = pd.to_datetime(vals, format=fmt, errors="coerce")
            if ts.notna().any():
                return ts
        return pd.to_datetime(vals, errors="coerce", dayfirst=True)

    return pd.to_datetime(vals, errors="coerce", dayfirst=True)


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


def _load_csv_file_incremental_in_chunks(
    conn: sqlite3.Connection,
    table: str,
    full_path: str,
    label: str,
    fn: str,
) -> None:
    it = _csv_chunk_iter(full_path, label, chunksize=CSV_CHUNK_SIZE)
    table_exists = _table_exists(conn, table)
    db_cols: list[str] | None = None
    ts_col: str | None = None
    max_ts: pd.Timestamp | None = None
    total_rows = 0
    inserted_rows = 0

    for chunk in it:
        if chunk is None or chunk.empty:
            continue
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
                # Keep behavior consistent with non-chunk path when schema changes.
                chunk.to_sql(table, conn, if_exists="replace", index=False)
                inserted_rows += len(chunk)
                db_cols = list(chunk.columns)
                continue

        aligned = chunk.reindex(columns=db_cols)
        work = aligned
        if RAW_LOADER_TIME_FILTER:
            if ts_col is None:
                det = _pick_best_timestamp_column(chunk, list(chunk.columns))
                ts_col = _match_column_name(db_cols, det)
                if ts_col is not None:
                    max_ts = _max_ts_in_column(conn, table, ts_col, label)
            if ts_col is not None and max_ts is not None and pd.notna(max_ts):
                ts_vals = _parse_timestamp_series(aligned[ts_col], label, ts_col)
                work = aligned.loc[(ts_vals > max_ts) & ts_vals.notna()].copy()

        if work.empty:
            continue
        work.to_sql(table, conn, if_exists="append", index=False)
        inserted_rows += len(work)

    print(
        f"[{label}] incremental {fn} -> table {table}: "
        f"+{inserted_rows} rows (file {total_rows} rows, chunked)"
    )


def _read_huawei_csv_best(path: str) -> pd.DataFrame | None:
    """
    Huawei exports often have a preamble (blank lines, 'GUL', 'Save Time', 'User Name')
    before the actual CSV header. Detect the true header row and parse from there.
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
            # Huawei exports may include preamble rows. The true header starts with "Time".
            if first_cell == "time" and line.count(",") >= 1:
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
    """Latest timestamp in ``col`` using SQL MAX when possible, else chunked scan."""
    try:
        n = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return None
    if n == 0:
        return None
    try:
        raw_val = conn.execute(f'SELECT MAX("{col}") FROM "{table}"').fetchone()[0]
    except Exception:
        raw_val = None
    if raw_val is not None and str(raw_val).strip() not in ('', 'None', 'NaT'):
        t = _parse_single_timestamp(raw_val, label, col)
        if pd.notna(t):
            return pd.Timestamp(t)
    best = pd.NaT
    try:
        for chunk in pd.read_sql_query(
            f'SELECT "{col}" AS v FROM "{table}"', conn, chunksize=65536
        ):
            ts = _parse_timestamp_series(chunk['v'], label, col)
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
        df_raw.to_sql(table, conn, if_exists='replace', index=False)
        print(
            f"[{label}] incremental {fn} -> table {table}: "
            f"columns changed, replaced ({len(df_raw)} rows)"
        )
        return

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

    files = [
        f
        for f in os.listdir(folder)
        if f.lower().endswith(_TABULAR_EXTS) and not f.startswith("~$")
    ]
    if not files:
        print(f"[{label}] no tabular files ({', '.join(_TABULAR_EXTS)}) in {folder}")
        return 0, 0

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
    finally:
        conn.close()
    return loaded, failed


def _incremental_for_label(label: str, scope: str = "hourly") -> bool:
    # Daily datasets should be full refreshes to avoid stale rows caused by
    # vendor date-format inconsistencies between snapshots.
    if str(scope).lower() == "daily":
        return False
    if label == 'metadata':
        return False
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
    return parser.parse_args()


def _apply_daily_retention_to_db(db_path: str, days: int, label: str) -> None:
    if days <= 0 or not os.path.isfile(db_path):
        return
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in tables:
            try:
                cols = _pragma_column_names(conn, table)
                ts_col = _pick_best_timestamp_column(pd.DataFrame(columns=cols), cols)
                ts_col = _match_column_name(cols, ts_col)
                if not ts_col:
                    continue
                doomed = []
                for chunk in pd.read_sql_query(
                    f'SELECT rowid AS _rid, "{ts_col}" AS _ts FROM "{table}"',
                    conn,
                    chunksize=50000,
                ):
                    if chunk.empty:
                        continue
                    ts = _parse_timestamp_series(chunk['_ts'], label, ts_col)
                    mask = ts.notna() & (ts < cutoff)
                    if mask.any():
                        doomed.extend(chunk.loc[mask, '_rid'].astype(int).tolist())
                if not doomed:
                    continue
                batch = 1000
                for i in range(0, len(doomed), batch):
                    part = doomed[i:i + batch]
                    ph = ",".join("?" for _ in part)
                    conn.execute(f'DELETE FROM "{table}" WHERE rowid IN ({ph})', part)
                print(f"[{label}] retention {table}: deleted {len(doomed)} rows older than {cutoff.date()}")
            except Exception as ex:
                print(f"[{label}] retention skipped on {table}: {ex}")
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    args = _parse_args()
    scope = args.scope
    raw_root = os.path.join(PROJECT_ROOT, "raw", "daily") if scope == "daily" else os.path.join(PROJECT_ROOT, "raw")
    is_daily = scope == "daily"

    mappings = [
        (os.path.join(raw_root, "huawei", "cells"), HUAWEI_PM_DAILY_DB if is_daily else HUAWEI_PM_DB, "huawei-cells"),
        (os.path.join(raw_root, "huawei", "groups"), HUAWEI_GROUPS_DAILY_DB if is_daily else HUAWEI_GROUPS_DB, "huawei-groups"),
        (os.path.join(raw_root, "nokia", "cells"), NOKIA_PM_DAILY_DB if is_daily else NOKIA_PM_DB, "nokia-cells"),
        (os.path.join(raw_root, "nokia", "groups"), NOKIA_GROUPS_DAILY_DB if is_daily else NOKIA_GROUPS_DB, "nokia-groups"),
    ]
    if not is_daily:
        mappings.append((os.path.join(PROJECT_ROOT, "raw", "metadata", "cells"), METADATA_DB, "metadata"))

    if args.category != "all":
        if args.category == "metadata":
            mappings = [m for m in mappings if m[2] == "metadata"]
        else:
            needle = f"-{args.category}"
            mappings = [m for m in mappings if needle in m[2]]

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
    print(f"[done] mode={mode} loaded_tables={total_loaded} failed_files={total_failed}")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
