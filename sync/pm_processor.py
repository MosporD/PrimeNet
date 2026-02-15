"""
PM Data Processor
Reads multi-cell hourly XLSX files and loads KPI data into the database.
"""

import sqlite3
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = 'ncm_users.db'


def process_pm_file(file_path, technology, column_map):
    """
    Process a PM XLSX file for a given technology and insert into cell_kpis.
    Returns (rows_inserted, rows_skipped, error_message).
    """
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to read PM file {file_path}: {e}')
        return 0, 0, str(e)

    # Reverse map: xlsx column -> db field
    reverse_map = {v: k for k, v in column_map.items() if v in df.columns}
    df = df.rename(columns=reverse_map)

    required = ['cell_name', 'timestamp']
    missing = [f for f in required if f not in df.columns]
    if missing:
        msg = f'PM file missing required columns (after mapping): {missing}. Found: {list(df.columns)}'
        logger.error(msg)
        return 0, 0, msg

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    inserted = 0
    skipped = 0

    kpi_fields = [
        'avg_users', 'data_volume_gb', 'rsrp', 'rsrq', 'sinr', 'cqi',
        'throughput_dl_mbps', 'throughput_ul_mbps', 'rrc_success_rate',
        'erab_success_rate', 'call_drop_rate', 'handover_success_rate',
        'availability_percent'
    ]

    for _, row in df.iterrows():
        cell_name = str(row.get('cell_name', '')).strip()
        if not cell_name:
            skipped += 1
            continue

        # Look up cell_id by name
        cursor.execute('SELECT cell_id FROM cells WHERE cell_name = ?', (cell_name,))
        cell = cursor.fetchone()
        if not cell:
            logger.debug(f'Cell not found in DB: {cell_name}, skipping.')
            skipped += 1
            continue

        cell_id = cell['cell_id']

        # Parse timestamp
        raw_ts = row.get('timestamp')
        try:
            ts = pd.to_datetime(raw_ts).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build KPI values dict
        kpi_values = {'cell_id': cell_id, 'timestamp': ts}
        for field in kpi_fields:
            val = row.get(field)
            kpi_values[field] = float(val) if pd.notna(val) else None

        # Upsert: replace existing record for same cell + timestamp
        placeholders = ', '.join(['?' for _ in kpi_values])
        columns = ', '.join(kpi_values.keys())
        cursor.execute(
            f'INSERT OR REPLACE INTO cell_kpis ({columns}) VALUES ({placeholders})',
            list(kpi_values.values())
        )
        inserted += 1

    conn.commit()
    conn.close()

    logger.info(f'PM [{technology}] processed: {inserted} inserted, {skipped} skipped.')
    return inserted, skipped, None


def run_pm_sync(downloaded_files, column_map):
    """
    Process all downloaded PM files (one per technology).
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        inserted, skipped, error = process_pm_file(file_path, tech, column_map)
        if error:
            summary[tech] = {'status': 'error', 'error': error}
        else:
            summary[tech] = {'status': 'ok', 'inserted': inserted, 'skipped': skipped}
    return summary
