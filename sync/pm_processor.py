"""
PM Data Processor
=================
Reads hourly KPI XLSX/XLS/CSV files and loads data into the appropriate PM database.

Nokia:  one file per technology → each file has many cells as rows
Huawei: single file, one sheet per technology (2G / 3G / 4G)

No column mapping configuration is required.  The code auto-detects which
column holds the cell name and which holds the timestamp by scanning column
names for well-known keywords.  All other columns are stored as-is using
the original header names, so charts can display them unchanged.
"""

import sqlite3
import logging
import pandas as pd
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, pm_table_name

logger = logging.getLogger(__name__)

# Keywords used to auto-detect the cell_name column (order matters — more specific first).
# Technology-specific prefixes must come before generic 'cell' so Nokia KPI columns
# like "Cell avail R" are not wrongly selected ahead of "NRCEL name" (5G) etc.
# Two-word 'cell name' catches Huawei's "Cell Name" before bare 'cell' fires on
# "Cell ID", "Cell FDD TDD Indication", "CellIndex", etc.
_CELL_KEYWORDS = ['nrcel', 'lncel', 'wcel', 'bts', 'cell name', 'cell_name', 'cellname', 'cell', 'name', 'trans']
# Keywords used to auto-detect the timestamp column.
# 'period start' (multi-word) targets Nokia's "Period start time" before bare 'time'
# fires on any other column containing 'time'.
_TS_KEYWORDS   = ['period start', 'period', 'time', 'date', 'start', 'timestamp']


# ---------------------------------------------------------------------------
# File reader — tries multiple engines so corrupted/old-format files work
# ---------------------------------------------------------------------------

def _load_pm_file(file_path):
    """
    Return a DataFrame from an XLSX, XLS, or CSV file.
    Nokia NetAct and Huawei U2000 often export files with a .xlsx extension
    that are actually HTML tables or tab/comma-delimited text in non-UTF-8
    encoding (latin-1, cp1252).  We try every plausible format.
    """
    # 1. Real XLSX (ZIP-based Office Open XML)
    try:
        return pd.read_excel(file_path, engine='openpyxl')
    except Exception:
        pass

    # 2. Old binary XLS (BIFF format)
    try:
        return pd.read_excel(file_path, engine='xlrd')
    except Exception:
        pass

    # 3. HTML table disguised as .xlsx (common Nokia NetAct export)
    try:
        dfs = pd.read_html(file_path, encoding='utf-8')
        if dfs and len(dfs[0].columns) > 1:
            return dfs[0]
    except Exception:
        pass
    try:
        dfs = pd.read_html(file_path, encoding='latin-1')
        if dfs and len(dfs[0].columns) > 1:
            return dfs[0]
    except Exception:
        pass

    # 4. Text file (tab / comma / semicolon) in various encodings
    for encoding in ('utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
        for sep in ('\t', ',', ';'):
            try:
                df = pd.read_csv(file_path, sep=sep, dtype=str, encoding=encoding)
                if len(df.columns) > 1:
                    logger.info(f'Loaded {file_path} as CSV (sep={sep!r}, enc={encoding})')
                    return df
            except Exception:
                pass

    # 5. Last resort — let pandas guess, with latin-1 (never fails on byte level)
    return pd.read_csv(file_path, dtype=str, encoding='latin-1')


# ---------------------------------------------------------------------------
# Auto-detect cell_name / timestamp columns
# ---------------------------------------------------------------------------

def _detect_col(columns, keywords):
    """Return the first column whose lower-case name contains any keyword."""
    col_lower = {c: str(c).lower() for c in columns}
    for kw in keywords:
        for col, low in col_lower.items():
            if kw in low:
                return col
    return None


def _resolve_key_cols(df):
    """
    Return (cell_name_col, timestamp_col).
    Falls back to column index 0 / 1 if auto-detect finds nothing.
    """
    cols = list(df.columns)
    cn = _detect_col(cols, _CELL_KEYWORDS)
    ts = _detect_col(cols, _TS_KEYWORDS)

    if cn is None:
        cn = cols[0]
        logger.warning(f'cell_name not detected — using first column: {cn!r}')
    if ts is None and len(cols) > 1:
        ts = cols[1]
        logger.warning(f'timestamp not detected — using second column: {ts!r}')
    elif ts is None:
        ts = cn

    return cn, ts


# ---------------------------------------------------------------------------
# Helpers: dynamic schema + insert
# ---------------------------------------------------------------------------

def _ensure_columns(conn, table, cols):
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    for col in cols:
        if col not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" REAL')


def _insert_df(db_path, df, technology):
    """
    Insert all rows of df into the technology-specific table (e.g. "4G_Hourly").
    df must have 'cell_name' and 'timestamp' columns.
    All other columns stored as-is with their original names.
    Returns (inserted, skipped).
    """
    table = pm_table_name(technology)
    kpi_cols = [c for c in df.columns if c not in ('cell_name', 'timestamp')]

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')   # allow readers while writing
    _ensure_columns(conn, table, kpi_cols)

    inserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        cell_name = str(row.get('cell_name', '')).strip()
        if not cell_name or cell_name == 'nan':
            skipped += 1
            continue

        raw_ts = row.get('timestamp')
        try:
            ts = pd.to_datetime(raw_ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        record = {'cell_name': cell_name, 'timestamp': ts}
        for col in kpi_cols:
            val = row.get(col)
            try:
                record[col] = float(val) if pd.notna(val) else None
            except (TypeError, ValueError):
                record[col] = None

        quoted_cols  = ', '.join(f'"{c}"' for c in record.keys())
        placeholders = ', '.join(['?'] * len(record))
        conn.execute(
            f'INSERT OR REPLACE INTO "{table}" ({quoted_cols}) VALUES ({placeholders})',
            list(record.values())
        )
        inserted += 1

    conn.commit()
    conn.close()
    logger.info(f'[{technology}] {db_path} → {table}: {inserted} inserted, {skipped} skipped.')
    return inserted, skipped


# ---------------------------------------------------------------------------
# Nokia: one file per technology
# ---------------------------------------------------------------------------

def process_nokia_pm_file(file_path, technology):
    """
    Process a Nokia PM file (XLSX, XLS, or CSV).
    Auto-detects cell_name and timestamp columns.
    Returns (inserted, skipped, error_message).
    """
    try:
        df = _load_pm_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read Nokia PM file {file_path}: {e}')
        return 0, 0, str(e)

    cn_col, ts_col = _resolve_key_cols(df)
    logger.info(f'Nokia PM [{technology}]: cell_name={cn_col!r}, timestamp={ts_col!r}')

    rename = {}
    if cn_col != 'cell_name':
        rename[cn_col] = 'cell_name'
    if ts_col != 'timestamp' and ts_col != cn_col:
        rename[ts_col] = 'timestamp'
    df = df.rename(columns=rename)

    if 'cell_name' not in df.columns:
        df = df.rename(columns={df.columns[0]: 'cell_name'})
    if 'timestamp' not in df.columns:
        df['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    inserted, skipped = _insert_df(NOKIA_PM_DB, df, technology)
    return inserted, skipped, None


def run_nokia_pm_sync(downloaded_files, column_maps=None):
    """
    downloaded_files = {technology: local_path or None}
    column_maps is accepted but ignored (kept for call-site compatibility).
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        inserted, skipped, error = process_nokia_pm_file(file_path, tech)
        summary[tech] = {'status': 'error', 'error': error} if error else {
            'status': 'ok', 'inserted': inserted, 'skipped': skipped
        }
    return summary


# ---------------------------------------------------------------------------
# Huawei: single XLSX with one sheet per technology
# ---------------------------------------------------------------------------

def process_huawei_pm_file(file_path, column_maps=None, sheet_tech_map=None):
    """
    Process a Huawei PM XLSX with multiple sheets.
    column_maps and sheet_tech_map are accepted but both ignored;
    auto-detection handles everything.
    Returns summary dict {sheet_name: {status, inserted, skipped, error}}.
    """
    try:
        xl = pd.ExcelFile(file_path, engine='openpyxl')
    except Exception:
        try:
            xl = pd.ExcelFile(file_path, engine='xlrd')
        except Exception as e:
            logger.error(f'Failed to open Huawei PM file {file_path}: {e}')
            return {'all': {'status': 'error', 'error': str(e)}}

    available_sheets = xl.sheet_names
    logger.info(f'Huawei PM sheets: {available_sheets}')

    summary = {}
    for sheet_name in available_sheets:
        try:
            df = xl.parse(sheet_name)
        except Exception as e:
            summary[sheet_name] = {'status': 'error', 'error': str(e)}
            continue

        cn_col, ts_col = _resolve_key_cols(df)
        logger.info(f'Huawei PM [{sheet_name}]: cell_name={cn_col!r}, timestamp={ts_col!r}')

        rename = {}
        if cn_col != 'cell_name':
            rename[cn_col] = 'cell_name'
        if ts_col != 'timestamp' and ts_col != cn_col:
            rename[ts_col] = 'timestamp'
        df = df.rename(columns=rename)

        if 'cell_name' not in df.columns:
            df = df.rename(columns={df.columns[0]: 'cell_name'})
        if 'timestamp' not in df.columns:
            df['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        inserted, skipped = _insert_df(HUAWEI_PM_DB, df, sheet_name)
        summary[sheet_name] = {'status': 'ok', 'inserted': inserted, 'skipped': skipped}

    return summary


# ---------------------------------------------------------------------------
# Legacy compat shim
# ---------------------------------------------------------------------------

def run_pm_sync(downloaded_files, column_map=None):
    """Compat shim — column_map ignored."""
    return run_nokia_pm_sync(downloaded_files)
