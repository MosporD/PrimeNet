"""
Import Local Files → Database
==============================
Reads local CSV / XLSX snapshots and imports them into the three databases:

  CSV  files         →  metadata.db  (sites + cells)
  Nokia XLSX files   →  nokia_pm.db  (cell_kpis)
  Huawei XLSX file   →  huawei_pm.db (cell_kpis)

File discovery — the script searches these directories in order:
  1. Project root
  2. sync_downloads/metadata/       (Metadata CSVs)
  3. sync_downloads/pm_nokia/       (Nokia PM XLSXs)
  4. sync_downloads/pm_huawei/      (Huawei PM XLSX)

No hardcoded filenames — it matches by pattern so newly downloaded
files (different date suffixes) are picked up automatically.

Usage:
    python scripts/import_local_files.py

Run from the project root directory.
"""

import os
import sys
import glob
import logging
import re
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync.db_migration import run_migrations
from sync.metadata_processor import process_metadata_file, seed_pm_cells_to_metadata
from sync.pm_processor import process_nokia_pm_file, process_huawei_pm_file, NOKIA_PM_DB, HUAWEI_PM_DB
from sync_config import (
    METADATA_CSV_COLUMN_MAPS,
    NOKIA_PM_COLUMN_MAPS, HUAWEI_PM_COLUMN_MAPS,
    METADATA_DB, PROJECT_ROOT
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search directories
# ---------------------------------------------------------------------------

DOWNLOADS = os.path.join(PROJECT_ROOT, 'sync_downloads')

METADATA_SEARCH_DIRS = [
    PROJECT_ROOT,
    os.path.join(DOWNLOADS, 'metadata'),
]

NOKIA_SEARCH_DIRS = [
    PROJECT_ROOT,
    os.path.join(DOWNLOADS, 'pm_nokia'),
]

HUAWEI_SEARCH_DIRS = [
    PROJECT_ROOT,
    os.path.join(DOWNLOADS, 'pm_huawei'),
]


# ---------------------------------------------------------------------------
# File finder helpers
# ---------------------------------------------------------------------------

def _find_files(search_dirs, pattern):
    """
    Glob for `pattern` in each directory. Returns all matches sorted newest-first.
    pattern is a glob pattern like '2G*.csv' or '*.xlsx'.
    """
    found = []
    for d in search_dirs:
        if os.path.isdir(d):
            found.extend(glob.glob(os.path.join(d, pattern)))
    # Sort by modification time, newest first
    found.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return found


def _find_latest(search_dirs, pattern):
    """Return the single newest file matching pattern, or None."""
    files = _find_files(search_dirs, pattern)
    return files[0] if files else None


def _infer_tech_from_name(filename):
    """
    Infer 2G / 3G / 4G-FDD / 4G-TDD / 5G / 4G from a filename stem.
    """
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    if '5G' in stem:
        return '5G'
    if '4G-TDD' in stem or '4G TDD' in stem or 'TDD' in stem:
        return '4G-TDD'
    if '4G-FDD' in stem or '4G FDD' in stem or 'FDD' in stem:
        return '4G-FDD'
    if '4G' in stem or 'LTE' in stem or re.search(r'L\d+', stem):
        return '4G'
    if '3G' in stem or 'WCDMA' in stem or 'UMTS' in stem:
        return '3G'
    if '2G' in stem or 'GSM' in stem:
        return '2G'
    return None


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
    """
    Find metadata CSV/XLSX files by pattern and import them.
    Searches for files starting with '2G', '3G', '4G', '5G' in metadata dirs.
    """
    logger.info('─── Importing metadata files ───')

    # Patterns to look for, mapped to technology labels.
    # The order matters: more specific patterns before general ones.
    TECH_PATTERNS = [
        ('5G',     ['5G*.csv',      '5G*.xlsx']),
        ('4G-TDD', ['*TDD*.csv',    '*TDD*.xlsx', '4G TDD*.csv', '4G TDD*.xlsx']),
        ('4G-FDD', ['*FDD*.csv',    '*FDD*.xlsx', '4G FDD*.csv', '4G FDD*.xlsx']),
        ('4G',     ['4G*.csv',      '4G*.xlsx', 'LTE*.csv', 'LTE*.xlsx']),
        ('3G',     ['3G*.csv',      '3G*.xlsx', 'WCDMA*.csv', 'UMTS*.csv']),
        ('2G',     ['2G*.csv',      '2G*.xlsx', 'GSM*.csv']),
    ]

    total_upserted = 0
    processed = set()  # avoid double-importing the same file

    for tech, patterns in TECH_PATTERNS:
        col_map = METADATA_CSV_COLUMN_MAPS.get(tech)
        if col_map is None:
            continue

        for pat in patterns:
            files = _find_files(METADATA_SEARCH_DIRS, pat)
            for fpath in files:
                real = os.path.realpath(fpath)
                if real in processed:
                    continue
                processed.add(real)

                logger.info(f'[{tech}] Importing {os.path.basename(fpath)} …')
                upserted, skipped, error = process_metadata_file(fpath, tech, col_map)
                if error:
                    logger.error(f'[{tech}] {error}')
                else:
                    logger.info(f'[{tech}] {upserted} upserted, {skipped} skipped.')
                    total_upserted += upserted
                break  # one file per tech is enough (newest found)

    if total_upserted == 0:
        logger.warning(
            'No metadata files found. Place CSV/XLSX exports in the project root or '
            'sync_downloads/metadata/ and re-run.'
        )
    else:
        logger.info(f'Metadata import complete: {total_upserted} total rows upserted.')

    return total_upserted


# ---------------------------------------------------------------------------
# Step 3 — Import Nokia PM Excel files
# ---------------------------------------------------------------------------

def import_nokia_pm():
    """
    Find Nokia PM Excel files by technology pattern and import them.
    Nokia exports one XLSX per technology with a sheet named '<TECH> Performance'.
    Falls back to the first sheet if that sheet name is not found.
    """
    logger.info('─── Importing Nokia PM Excel files ───')

    NOKIA_TECHS = ['2G', '3G', '4G', '5G']
    NOKIA_PATTERNS = {
        '2G': ['2G*.xlsx', '2G*.xls'],
        '3G': ['3G*.xlsx', '3G*.xls'],
        '4G': ['4G*.xlsx', '4G*.xls'],
        '5G': ['5G*.xlsx', '5G*.xls'],
    }

    total_inserted = 0
    processed = set()

    for tech in NOKIA_TECHS:
        for pat in NOKIA_PATTERNS[tech]:
            files = _find_files(NOKIA_SEARCH_DIRS, pat)
            for fpath in files:
                real = os.path.realpath(fpath)
                if real in processed:
                    continue
                processed.add(real)

                logger.info(f'[Nokia {tech}] Importing {os.path.basename(fpath)} …')
                inserted, skipped, error = process_nokia_pm_file(fpath, tech)
                if error:
                    logger.error(f'[Nokia {tech}] {error}')
                else:
                    logger.info(f'[Nokia {tech}] {inserted} inserted, {skipped} skipped.')
                    total_inserted += inserted
                break  # one file per tech

    if total_inserted == 0:
        logger.warning(
            'No Nokia PM files found. Place XLSX exports in the project root or '
            'sync_downloads/pm_nokia/ and re-run.'
        )
    else:
        logger.info(f'Nokia PM import complete: {total_inserted} total rows inserted.')

    return total_inserted


# ---------------------------------------------------------------------------
# Step 4 — Import Huawei PM Excel file
# ---------------------------------------------------------------------------

def import_huawei_pm():
    """
    Find Huawei PM Excel file (single file with sheets 2G/3G/4G) and import.
    Tries 'Performance.xlsx' first, then any *.xlsx in the Huawei search dirs.
    """
    logger.info('─── Importing Huawei PM Excel file ───')

    # Try named file first, then any xlsx
    path = _find_latest(HUAWEI_SEARCH_DIRS, 'Performance.xlsx')
    if not path:
        path = _find_latest(HUAWEI_SEARCH_DIRS, '*.xlsx')

    if not path:
        logger.warning(
            'No Huawei PM file found. Place Performance.xlsx in the project root or '
            'sync_downloads/pm_huawei/ and re-run.'
        )
        return 0

    logger.info(f'[Huawei] Importing {os.path.basename(path)} …')
    summary = process_huawei_pm_file(path)
    total_inserted = 0
    for sheet, result in summary.items():
        if result.get('status') == 'ok':
            logger.info(f'[Huawei/{sheet}] {result["inserted"]} inserted, {result["skipped"]} skipped.')
            total_inserted += result.get('inserted', 0)
        else:
            logger.error(f'[Huawei/{sheet}] {result.get("error")}')

    logger.info(f'Huawei PM import complete: {total_inserted} total rows inserted.')
    return total_inserted


# ---------------------------------------------------------------------------
# Step 5 — Seed metadata.db with PM cell placeholders
# ---------------------------------------------------------------------------

def seed_metadata():
    """
    For every cell in the PM databases not yet in metadata.db,
    insert placeholder site + cell rows so the performance JOIN works.
    """
    logger.info('─── Seeding metadata from PM databases ───')
    n = seed_pm_cells_to_metadata(NOKIA_PM_DB, 'Nokia')
    h = seed_pm_cells_to_metadata(HUAWEI_PM_DB, 'Huawei')
    logger.info(f'Seeded {n} Nokia cells + {h} Huawei cells into metadata.db.')
    return n + h


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_schema()
    meta_rows   = import_metadata()
    nokia_rows  = import_nokia_pm()
    huawei_rows = import_huawei_pm()
    seeded_rows = seed_metadata()

    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    logger.info('Import finished:')
    logger.info(f'  metadata.db   →  {meta_rows} site/cell rows upserted')
    logger.info(f'                    + {seeded_rows} PM cells seeded as placeholders')
    logger.info(f'  nokia_pm.db   →  {nokia_rows} KPI rows inserted')
    logger.info(f'  huawei_pm.db  →  {huawei_rows} KPI rows inserted')
    logger.info('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    if meta_rows + nokia_rows + huawei_rows == 0:
        logger.info('')
        logger.info('No files were imported. To use this script:')
        logger.info('  • Place metadata CSV exports  in: sync_downloads/metadata/')
        logger.info('  • Place Nokia PM XLSX exports in: sync_downloads/pm_nokia/')
        logger.info('  • Place Huawei Performance.xlsx in: sync_downloads/pm_huawei/')
        logger.info('  • Or place any of the above directly in the project root.')


if __name__ == '__main__':
    main()
