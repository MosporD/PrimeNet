"""
Import Local Files → Database
==============================
One-time (and re-runnable) script that reads the local CSV and XLSX
snapshot files and imports them into the three-database architecture:

  CSV  files  →  metadata.db  (sites + cells)
  XLSX files  →  nokia_pm.db  (cell_kpis)

Usage:
    python scripts/import_local_files.py

Run from the project root directory.
"""

import os
import sys
import logging

# Allow imports from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync.db_migration import run_migrations
from sync.metadata_processor import process_metadata_file
from sync.pm_processor import process_nokia_pm_file
from sync_config import METADATA_CSV_COLUMN_MAPS, NOKIA_PM_COLUMN_MAP

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

# Nokia PM Excel files; only 4G is a proper .xlsx — others are encrypted.
# Add file paths here as they become available/decrypted.
NOKIA_PM_EXCEL_FILES = {
    '4G': '4G-2026_02_15-12_49_23__178.xlsx',
    # '2G': '2G-42729-2026_02_15-12_00_04__458.xlsx',   # encrypted
    # '3G': '3G-42727-2026_02_15-12_00_16__894.xlsx',   # encrypted
    # '5G': '5G-42731-2026_02_15-12_00_24__466.xlsx',   # encrypted
}

# Nokia 4G Excel sheet name that contains the KPI data
NOKIA_4G_SHEET = '4G Performance'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abs(filename):
    """Return absolute path relative to project root."""
    return os.path.join(BASE_DIR, filename)


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
    total_skipped = 0

    for tech, filename in METADATA_CSV_FILES.items():
        path = _abs(filename)
        if not os.path.exists(path):
            logger.warning(f'[{tech}] File not found, skipping: {path}')
            continue

        col_map = METADATA_CSV_COLUMN_MAPS.get(tech)
        if col_map is None:
            logger.warning(f'[{tech}] No column map defined in METADATA_CSV_COLUMN_MAPS, skipping.')
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
    import pandas as pd

    logger.info('─── Importing Nokia PM Excel files ───')
    total_inserted = 0

    for tech, filename in NOKIA_PM_EXCEL_FILES.items():
        path = _abs(filename)
        if not os.path.exists(path):
            logger.warning(f'[Nokia {tech}] File not found, skipping: {path}')
            continue

        logger.info(f'[Nokia {tech}] Reading {filename} …')

        # The 4G file has multiple sheets; pick the KPI sheet
        if tech == '4G':
            try:
                df = pd.read_excel(path, sheet_name=NOKIA_4G_SHEET, engine='openpyxl')
            except Exception as e:
                logger.error(f'[Nokia {tech}] Failed to read sheet "{NOKIA_4G_SHEET}": {e}')
                continue

            # Build a single-sheet temp file isn't needed — pass the DataFrame directly
            # to _insert_df after renaming columns via the column map.
            from sync.pm_processor import _insert_df, NOKIA_PM_DB

            # Rename columns: map XLSX header → DB field
            reverse_map = {
                v: k
                for k, v in NOKIA_PM_COLUMN_MAP.items()
                if v and v in df.columns
            }
            df = df.rename(columns=reverse_map)

            missing = [f for f in ('cell_name', 'timestamp') if f not in df.columns]
            if missing:
                logger.error(f'[Nokia {tech}] Missing columns {missing} after mapping. '
                             f'Found: {list(df.columns)}')
                continue

            # Coerce all KPI columns to numeric; non-numeric cells become NaN → stored as NULL
            from sync.pm_processor import KPI_FIELDS
            for kpi in KPI_FIELDS:
                if kpi in df.columns:
                    df[kpi] = pd.to_numeric(df[kpi], errors='coerce')

            # Drop rows with missing/invalid cell names (summary / header rows)
            df = df[df['cell_name'].notna()]
            df = df[df['cell_name'].astype(str).str.strip().str.lower() != 'nan']
            df = df[df['cell_name'].astype(str).str.strip() != '']

            inserted, skipped = _insert_df(NOKIA_PM_DB, df, tech)
            logger.info(f'[Nokia {tech}] Done — {inserted} inserted, {skipped} skipped.')
            total_inserted += inserted
        else:
            # For 2G / 3G / 5G: use the standard processor (single-sheet XLSX expected)
            inserted, skipped, error = process_nokia_pm_file(path, tech, NOKIA_PM_COLUMN_MAP)
            if error:
                logger.error(f'[Nokia {tech}] Import failed: {error}')
            else:
                logger.info(f'[Nokia {tech}] Done — {inserted} inserted, {skipped} skipped.')
                total_inserted += inserted

    logger.info(f'Nokia PM import complete: {total_inserted} total rows inserted.')
    return total_inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_schema()
    meta_rows  = import_metadata()
    pm_rows    = import_nokia_pm()

    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    logger.info(f'Import finished:')
    logger.info(f'  metadata.db  →  {meta_rows} site/cell rows upserted')
    logger.info(f'  nokia_pm.db  →  {pm_rows} KPI rows inserted')
    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')


if __name__ == '__main__':
    main()
