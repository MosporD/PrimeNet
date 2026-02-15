"""
PM Data Processor
=================
Reads hourly KPI XLSX files and loads data into the appropriate PM database.

Nokia:  one file per technology → each file has many cells as rows
Huawei: single file, one sheet per technology (2G / 3G / 4G)

Column maps only need to identify cell_name and timestamp.
All other columns are stored as-is using the original header names.
The DB schema evolves automatically — new columns are added via ALTER TABLE.
"""

import sqlite3
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

NOKIA_PM_DB  = 'nokia_pm.db'
HUAWEI_PM_DB = 'huawei_pm.db'


# ---------------------------------------------------------------------------
# Helpers: dynamic schema evolution + insert
# ---------------------------------------------------------------------------

def _ensure_columns(conn, table, cols):
    """Add any missing columns to the table (as REAL). Quoted to handle special chars."""
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    for col in cols:
        if col not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN "{col}" REAL')


def _insert_df(db_path, df, technology):
    """
    Insert all rows of df into cell_kpis.
    df must already have 'cell_name' and 'timestamp' columns.
    All other columns are treated as KPI fields and stored as-is.
    Returns (inserted, skipped).
    """
    kpi_cols = [c for c in df.columns if c not in ('cell_name', 'timestamp')]

    conn = sqlite3.connect(db_path)
    _ensure_columns(conn, 'cell_kpis', kpi_cols)

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
            record[col] = float(val) if pd.notna(val) else None

        quoted_cols  = ', '.join(f'"{c}"' for c in record.keys())
        placeholders = ', '.join(['?'] * len(record))
        conn.execute(
            f'INSERT OR REPLACE INTO cell_kpis ({quoted_cols}) VALUES ({placeholders})',
            list(record.values())
        )
        inserted += 1

    conn.commit()
    conn.close()
    logger.info(f'[{technology}] {db_path}: {inserted} inserted, {skipped} skipped.')
    return inserted, skipped


# ---------------------------------------------------------------------------
# Nokia: one XLSX per technology, rows = cells
# ---------------------------------------------------------------------------

def process_nokia_pm_file(file_path, technology, column_map):
    """
    Process a Nokia PM XLSX file (one file per technology).
    column_map only needs 'cell_name' and 'timestamp' keys.
    Returns (inserted, skipped, error_message).
    """
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to read Nokia PM file {file_path}: {e}')
        return 0, 0, str(e)

    # Rename cell_name and timestamp columns only
    rename = {}
    cn = column_map.get('cell_name')
    ts = column_map.get('timestamp')
    if cn and cn in df.columns and cn != 'cell_name':
        rename[cn] = 'cell_name'
    if ts and ts in df.columns and ts != 'timestamp':
        rename[ts] = 'timestamp'
    df = df.rename(columns=rename)

    missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
    if missing:
        msg = f'Nokia PM [{technology}] missing {missing}. Found: {list(df.columns)}'
        logger.error(msg)
        return 0, 0, msg

    inserted, skipped = _insert_df(NOKIA_PM_DB, df, technology)
    return inserted, skipped, None


def run_nokia_pm_sync(downloaded_files, column_maps):
    """
    downloaded_files = {technology: local_path or None}
    column_maps      = {technology: {'cell_name': '...', 'timestamp': '...'}}
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        col_map = column_maps.get(tech, {})
        inserted, skipped, error = process_nokia_pm_file(file_path, tech, col_map)
        summary[tech] = {'status': 'error', 'error': error} if error else {
            'status': 'ok', 'inserted': inserted, 'skipped': skipped
        }
    return summary


# ---------------------------------------------------------------------------
# Huawei: single XLSX with one sheet per technology
# ---------------------------------------------------------------------------

def process_huawei_pm_file(file_path, column_maps, sheet_tech_map=None):
    """
    Process a Huawei PM XLSX with multiple sheets (one per technology).
    column_maps    = {technology: {'cell_name': '...', 'timestamp': '...'}}
    sheet_tech_map = {'2G': 'SheetName2G', ...}
    Returns summary dict {tech: {status, inserted, skipped, error}}.
    """
    if sheet_tech_map is None:
        sheet_tech_map = {'2G': '2G', '3G': '3G', '4G': '4G'}

    try:
        xl = pd.ExcelFile(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to open Huawei PM file {file_path}: {e}')
        return {t: {'status': 'error', 'error': str(e)} for t in sheet_tech_map}

    available_sheets = xl.sheet_names
    logger.info(f'Huawei PM file sheets: {available_sheets}')

    summary = {}
    for tech, sheet_name in sheet_tech_map.items():
        col_map = column_maps.get(tech, {})

        # Match sheet name (case-insensitive)
        actual_sheet = None
        for s in available_sheets:
            if s == sheet_name or s.lower() == sheet_name.lower():
                actual_sheet = s
                break

        if not actual_sheet:
            logger.warning(f'Sheet "{sheet_name}" not found in Huawei PM file. Available: {available_sheets}')
            summary[tech] = {'status': 'skipped', 'reason': f'Sheet "{sheet_name}" not found'}
            continue

        try:
            df = xl.parse(actual_sheet)
        except Exception as e:
            summary[tech] = {'status': 'error', 'error': str(e)}
            continue

        # Rename cell_name and timestamp only
        rename = {}
        cn = col_map.get('cell_name')
        ts = col_map.get('timestamp')
        if cn and cn in df.columns and cn != 'cell_name':
            rename[cn] = 'cell_name'
        if ts and ts in df.columns and ts != 'timestamp':
            rename[ts] = 'timestamp'
        df = df.rename(columns=rename)

        missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
        if missing:
            msg = f'Huawei PM sheet [{sheet_name}] missing {missing}. Found: {list(df.columns)}'
            logger.error(msg)
            summary[tech] = {'status': 'error', 'error': msg}
            continue

        inserted, skipped = _insert_df(HUAWEI_PM_DB, df, tech)
        summary[tech] = {'status': 'ok', 'inserted': inserted, 'skipped': skipped}

    return summary


# ---------------------------------------------------------------------------
# Legacy compat shim
# ---------------------------------------------------------------------------

def run_pm_sync(downloaded_files, column_map):
    """Compat shim — calls Nokia processor."""
    return run_nokia_pm_sync(downloaded_files, column_map)
