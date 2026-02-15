"""
Import Local Files → Database
==============================
One-time (and re-runnable) script that reads the local CSV and XLSX
snapshot files and imports them into the three-database architecture:

  CSV  files         →  metadata.db  (sites + cells)
  Nokia XLSX files   →  nokia_pm.db  (cell_kpis)
  Huawei XLSX file   →  huawei_pm.db (cell_kpis)

Usage:
    python scripts/import_local_files.py

Run from the project root directory.
"""

import os
import sys
import logging
import pandas as pd

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync.db_migration import run_migrations
from sync.metadata_processor import process_metadata_file
from sync.pm_processor import _insert_df, NOKIA_PM_DB, HUAWEI_PM_DB, KPI_FIELDS
from sync_config import METADATA_CSV_COLUMN_MAPS, NOKIA_PM_COLUMN_MAPS, HUAWEI_PM_COLUMN_MAPS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File paths (relative to project root)
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

METADATA_CSV_FILES = {
    '2G':     '2G - 2026-02-15.csv',
    '3G':     '3G - 2026-02-15.csv',
    '4G-FDD': '4G FDD - 2026-02-15.csv',
    '4G-TDD': '4G TDD - 2026-02-15.csv',
    '5G':     '5G - 2026-02-15.csv',
}

# Nokia PM: one file per technology; each has a single KPI sheet named "<TECH> Performance"
NOKIA_PM_EXCEL_FILES = {
    '2G': '2G-42729-2026_02_15-12_00_04__458.xlsx',
    '3G': '3G-42727-2026_02_15-12_00_16__894.xlsx',
    '4G': '4G-2026_02_15-12_49_23__178.xlsx',
    '5G': '5G-42731-2026_02_15-12_00_24__466.xlsx',
}

# Huawei PM: single file with one sheet per technology
HUAWEI_PM_FILE   = 'Performance.xlsx'
HUAWEI_PM_SHEETS = {'4G': '4G', '3G': '3G', '2G': '2G'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abs(filename):
    """Return absolute path relative to project root."""
    return os.path.join(BASE_DIR, filename)


def _import_pm_df(df, tech, db_path, col_map, label):
    """
    Rename columns using col_map, coerce KPI fields to numeric,
    drop invalid rows, then insert into db_path.
    Returns rows inserted.
    """
    # Rename XLSX header → DB field name
    rename = {v: k for k, v in col_map.items() if v and v in df.columns}
    df = df.rename(columns=rename)

    missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
    if missing:
        logger.error(f'[{label}] Missing columns {missing} after mapping. '
                     f'Found: {list(df.columns)}')
        return 0

    # Coerce KPI columns to numeric; text values (totals, headers) → NaN → NULL
    for kpi in KPI_FIELDS:
        if kpi in df.columns:
            df[kpi] = pd.to_numeric(df[kpi], errors='coerce')

    # Drop rows with missing/invalid cell names
    df = df[df['cell_name'].notna()]
    df = df[~df['cell_name'].astype(str).str.strip().str.lower().isin(['nan', ''])]

    inserted, skipped = _insert_df(db_path, df, tech)
    logger.info(f'[{label}] Done — {inserted} inserted, {skipped} skipped.')
    return inserted


# ---------------------------------------------------------------------------
# Step 1 — Ensure DB schema exists
# ---------------------------------------------------------------------------

def ensure_schema():
    logger.info('Running DB migrations …')
    run_migrations()
    logger.info('Schema ready.')


# ---------------------------------------------------------------------------
# Step 2 — Import metadata CSVs
# ---------------------------------------------------------------------------

def import_metadata():
    logger.info('─── Importing metadata CSV files ───')
    total_upserted = 0
    total_skipped  = 0

    for tech, filename in METADATA_CSV_FILES.items():
        path = _abs(filename)
        if not os.path.exists(path):
            logger.warning(f'[{tech}] File not found, skipping: {path}')
            continue

        col_map = METADATA_CSV_COLUMN_MAPS.get(tech)
        if col_map is None:
            logger.warning(f'[{tech}] No column map defined, skipping.')
            continue

        logger.info(f'[{tech}] Reading {filename} …')
        upserted, skipped, error = process_metadata_file(path, tech, col_map)
        if error:
            logger.error(f'[{tech}] Import failed: {error}')
        else:
            logger.info(f'[{tech}] Done — {upserted} upserted, {skipped} skipped.')
            total_upserted += upserted
            total_skipped  += skipped

    logger.info(f'Metadata import complete: {total_upserted} total upserted, {total_skipped} skipped.')
    return total_upserted


# ---------------------------------------------------------------------------
# Step 3 — Import Nokia PM Excel files
# ---------------------------------------------------------------------------

def import_nokia_pm():
    logger.info('─── Importing Nokia PM Excel files ───')
    total_inserted = 0

    for tech, filename in NOKIA_PM_EXCEL_FILES.items():
        path = _abs(filename)
        if not os.path.exists(path):
            logger.warning(f'[Nokia {tech}] File not found, skipping: {path}')
            continue

        col_map = NOKIA_PM_COLUMN_MAPS.get(tech)
        if col_map is None:
            logger.warning(f'[Nokia {tech}] No column map defined, skipping.')
            continue

        sheet_name = f'{tech} Performance'
        logger.info(f'[Nokia {tech}] Reading sheet "{sheet_name}" from {filename} …')
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl')
        except Exception as e:
            logger.error(f'[Nokia {tech}] Failed to read file: {e}')
            continue

        inserted = _import_pm_df(df, tech, NOKIA_PM_DB, col_map, f'Nokia {tech}')
        total_inserted += inserted

    logger.info(f'Nokia PM import complete: {total_inserted} total rows inserted.')
    return total_inserted


# ---------------------------------------------------------------------------
# Step 4 — Import Huawei PM Excel file
# ---------------------------------------------------------------------------

def import_huawei_pm():
    logger.info('─── Importing Huawei PM Excel file ───')
    path = _abs(HUAWEI_PM_FILE)
    if not os.path.exists(path):
        logger.warning(f'Huawei PM file not found, skipping: {path}')
        return 0

    total_inserted = 0

    for tech, sheet_name in HUAWEI_PM_SHEETS.items():
        col_map = HUAWEI_PM_COLUMN_MAPS.get(tech)
        if col_map is None:
            logger.warning(f'[Huawei {tech}] No column map defined, skipping.')
            continue

        logger.info(f'[Huawei {tech}] Reading sheet "{sheet_name}" from {HUAWEI_PM_FILE} …')
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl')
        except Exception as e:
            logger.error(f'[Huawei {tech}] Failed to read sheet "{sheet_name}": {e}')
            continue

        inserted = _import_pm_df(df, tech, HUAWEI_PM_DB, col_map, f'Huawei {tech}')
        total_inserted += inserted

    logger.info(f'Huawei PM import complete: {total_inserted} total rows inserted.')
    return total_inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_schema()
    meta_rows   = import_metadata()
    nokia_rows  = import_nokia_pm()
    huawei_rows = import_huawei_pm()

    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    logger.info('Import finished:')
    logger.info(f'  metadata.db   →  {meta_rows} site/cell rows upserted')
    logger.info(f'  nokia_pm.db   →  {nokia_rows} KPI rows inserted')
    logger.info(f'  huawei_pm.db  →  {huawei_rows} KPI rows inserted')
    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')


if __name__ == '__main__':
    main()
