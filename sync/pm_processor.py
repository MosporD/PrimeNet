"""
PM Data Processor
=================
Reads hourly KPI XLSX files and loads data into the appropriate PM database.

Nokia:  one file per technology → each file has many cells as rows
Huawei: single file, one sheet per technology (2G / 3G / 4G)

Both processors write to vendor-specific DBs using cell_name as the
cross-database join key (no FK to metadata.db needed here).
"""

import sqlite3
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

NOKIA_PM_DB  = 'nokia_pm.db'
HUAWEI_PM_DB = 'huawei_pm.db'

KPI_FIELDS = [
    'avg_users', 'data_volume_gb', 'rsrp', 'rsrq', 'sinr', 'cqi',
    'throughput_dl_mbps', 'throughput_ul_mbps',
    'rrc_success_rate', 'erab_success_rate',
    'call_drop_rate', 'handover_success_rate',
    'availability_percent',
]


# ---------------------------------------------------------------------------
# Shared: insert a DataFrame of KPI rows into a PM DB
# ---------------------------------------------------------------------------

def _insert_df(db_path, df, technology):
    """
    Expects df to already have columns: cell_name, timestamp, + KPI fields.
    Inserts via REPLACE to honour the UNIQUE(cell_name, timestamp) constraint.
    Returns (inserted, skipped).
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    inserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        cell_name = str(row.get('cell_name', '')).strip()
        if not cell_name:
            skipped += 1
            continue

        raw_ts = row.get('timestamp')
        try:
            ts = pd.to_datetime(raw_ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        record = {'cell_name': cell_name, 'timestamp': ts}
        for field in KPI_FIELDS:
            val = row.get(field)
            record[field] = float(val) if pd.notna(val) else None

        cols   = ', '.join(record.keys())
        places = ', '.join(['?'] * len(record))
        cursor.execute(
            f'INSERT OR REPLACE INTO cell_kpis ({cols}) VALUES ({places})',
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
    Returns (inserted, skipped, error_message).
    """
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to read Nokia PM file {file_path}: {e}')
        return 0, 0, str(e)

    reverse_map = {v: k for k, v in column_map.items() if v in df.columns}
    df = df.rename(columns=reverse_map)

    missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
    if missing:
        msg = f'Nokia PM [{technology}] missing columns {missing}. Found: {list(df.columns)}'
        logger.error(msg)
        return 0, 0, msg

    inserted, skipped = _insert_df(NOKIA_PM_DB, df, technology)
    return inserted, skipped, None


def run_nokia_pm_sync(downloaded_files, column_map):
    """
    downloaded_files = {technology: local_path or None}
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        inserted, skipped, error = process_nokia_pm_file(file_path, tech, column_map)
        summary[tech] = {'status': 'error', 'error': error} if error else {
            'status': 'ok', 'inserted': inserted, 'skipped': skipped
        }
    return summary


# ---------------------------------------------------------------------------
# Huawei: single XLSX with one sheet per technology
# ---------------------------------------------------------------------------

def process_huawei_pm_file(file_path, column_map, sheet_tech_map=None):
    """
    Process a Huawei PM XLSX with multiple sheets (one per technology).
    sheet_tech_map = {'2G': 'SheetName2G', '3G': 'SheetName3G', '4G': 'SheetName4G'}
    If None, defaults to {'2G': '2G', '3G': '3G', '4G': '4G'}.

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
        # Try exact match first, then case-insensitive
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

        reverse_map = {v: k for k, v in column_map.items() if v in df.columns}
        df = df.rename(columns=reverse_map)

        missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
        if missing:
            msg = f'Huawei PM sheet [{sheet_name}] missing columns {missing}. Found: {list(df.columns)}'
            logger.error(msg)
            summary[tech] = {'status': 'error', 'error': msg}
            continue

        inserted, skipped = _insert_df(HUAWEI_PM_DB, df, tech)
        summary[tech] = {'status': 'ok', 'inserted': inserted, 'skipped': skipped}

    return summary


# ---------------------------------------------------------------------------
# Legacy compat shim (used by old scheduler references)
# ---------------------------------------------------------------------------

def run_pm_sync(downloaded_files, column_map):
    """Compat shim — calls Nokia processor. Use run_nokia_pm_sync() directly."""
    return run_nokia_pm_sync(downloaded_files, column_map)
