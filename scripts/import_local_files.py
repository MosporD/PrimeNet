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
from sync.pm_processor import _insert_df, NOKIA_PM_DB, HUAWEI_PM_DB
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

    # Coerce all non-key columns to numeric; text/total rows → NaN → NULL
    for col in df.columns:
        if col not in ('cell_name', 'timestamp'):
            df[col] = pd.to_numeric(df[col], errors='coerce')

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
# Step 5 — Seed metadata.db with PM cells that are not already there
# The app JOINs cells ↔ cell_kpis on cell_name, so every PM cell must
# exist in metadata.db for its data to appear in the UI.
# ---------------------------------------------------------------------------

# Technology each Nokia Excel file covers
NOKIA_FILE_TECH = {
    '2G': '2G',
    '3G': '3G',
    '4G': '4G',
    '5G': '5G',
}

# Technology each Huawei sheet covers
HUAWEI_SHEET_TECH = {
    '4G': '4G',
    '3G': '3G',
    '2G': '2G',
}


def _pm_site_id(cell_name):
    """Extract site_id from a PM cell name (numeric prefix before first - or _)."""
    import re
    m = re.match(r'^(\d+)', cell_name)
    return m.group(1) if m else None


def _pm_site_name(cell_name):
    """Derive site name by stripping the trailing sector suffix (-A, -B1, _A1, etc.)."""
    import re
    return re.sub(r'[-_][A-Za-z]\d*$', '', cell_name)


def seed_metadata_from_pm():
    """
    For every cell_name in nokia_pm.db / huawei_pm.db that is missing from
    metadata.db, insert a placeholder site + cells row so the JOIN works in the app.
    """
    import sqlite3 as _sq

    meta = _sq.connect(_abs('metadata.db'))
    nokia_pm = _sq.connect(_abs('nokia_pm.db'))
    huawei_pm = _sq.connect(_abs('huawei_pm.db'))

    existing_cells = {r[0] for r in meta.execute("SELECT cell_name FROM cells").fetchall()}
    existing_sites = {r[0] for r in meta.execute("SELECT site_id FROM sites").fetchall()}

    seeded = 0

    def _seed_cell(cell_name, tech, vendor):
        nonlocal seeded
        if cell_name in existing_cells:
            return
        site_id   = _pm_site_id(cell_name)
        site_name = _pm_site_name(cell_name)
        # Ensure a placeholder site exists so the JOIN works
        if site_id and site_id not in existing_sites:
            meta.execute(
                "INSERT OR IGNORE INTO sites (site_id, site_name, vendor, status) "
                "VALUES (?, ?, ?, 'Active')",
                (site_id, site_name, vendor)
            )
            existing_sites.add(site_id)
        meta.execute(
            "INSERT OR IGNORE INTO cells (cell_name, site_id, technology, vendor, status) "
            "VALUES (?, ?, ?, ?, 'Active')",
            (cell_name, site_id, tech, vendor)
        )
        existing_cells.add(cell_name)
        seeded += 1

    # Nokia — we know cell names per tech from the Excel files
    for tech, filename in NOKIA_PM_EXCEL_FILES.items():
        path = _abs(filename)
        if not os.path.exists(path):
            continue
        col_map = NOKIA_PM_COLUMN_MAPS.get(tech, {})
        cell_col = col_map.get('cell_name')
        if not cell_col:
            continue
        sheet_name = f'{tech} Performance'
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl',
                               usecols=[cell_col])
        except Exception:
            continue
        for cell_name in df[cell_col].dropna().unique():
            cell_name = str(cell_name).strip()
            if not cell_name or cell_name.lower() == 'nan':
                continue
            _seed_cell(cell_name, NOKIA_FILE_TECH[tech], 'Nokia')

    # Huawei — from Performance.xlsx sheets
    perf_path = _abs(HUAWEI_PM_FILE)
    if os.path.exists(perf_path):
        for tech, sheet_name in HUAWEI_PM_SHEETS.items():
            col_map = HUAWEI_PM_COLUMN_MAPS.get(tech, {})
            cell_col = col_map.get('cell_name')
            if not cell_col:
                continue
            try:
                df = pd.read_excel(perf_path, sheet_name=sheet_name,
                                   engine='openpyxl', usecols=[cell_col])
            except Exception:
                continue
            for cell_name in df[cell_col].dropna().unique():
                cell_name = str(cell_name).strip()
                if not cell_name or cell_name.lower() == 'nan':
                    continue
                _seed_cell(cell_name, HUAWEI_SHEET_TECH[tech], 'Huawei')

    meta.commit()
    meta.close()
    nokia_pm.close()
    huawei_pm.close()

    logger.info(f'Metadata seeding complete: {seeded} PM cells added to metadata.db.')
    return seeded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_schema()
    meta_rows   = import_metadata()
    nokia_rows  = import_nokia_pm()
    huawei_rows = import_huawei_pm()
    seeded_rows = seed_metadata_from_pm()

    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    logger.info('Import finished:')
    logger.info(f'  metadata.db   →  {meta_rows} site/cell rows upserted')
    logger.info(f'                    + {seeded_rows} PM cells seeded')
    logger.info(f'  nokia_pm.db   →  {nokia_rows} KPI rows inserted')
    logger.info(f'  huawei_pm.db  →  {huawei_rows} KPI rows inserted')
    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')


if __name__ == '__main__':
    main()
