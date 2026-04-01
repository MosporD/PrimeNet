"""
DB Migration — Three-Database Architecture
==========================================
metadata.db   → sites, cells, sectors for ALL vendors (source of truth)
nokia_pm.db   → Nokia hourly KPI rows keyed by cell_name + timestamp
huawei_pm.db  → Huawei hourly KPI rows keyed by cell_name + timestamp

Cell linkage: cell_name is the shared key across all three DBs.
The performance API queries metadata.db and ATTACHes the relevant PM db
to do cross-db JOINs purely in SQLite.
"""

import sqlite3
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import METADATA_DB, NOKIA_PM_DB, HUAWEI_PM_DB, NCMUSERS_DB as APP_DB, PM_TECHNOLOGIES, pm_table_name

logger = logging.getLogger(__name__)


_KPI_COLS = '''
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_name TEXT    NOT NULL,
    timestamp TEXT    NOT NULL
'''


def _create_pm_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for tech in PM_TECHNOLOGIES:
        table = pm_table_name(tech)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS "{table}" (
                {_KPI_COLS},
                UNIQUE (cell_name, timestamp) ON CONFLICT REPLACE
            )
        ''')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_cell_ts" ON "{table}" (cell_name, timestamp)')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_ts"      ON "{table}" (timestamp)')
    conn.commit()
    conn.close()
    logger.info(f'{db_path} ready ({", ".join(pm_table_name(t) for t in PM_TECHNOLOGIES)}).')


def _create_metadata_db():
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            site_id    TEXT PRIMARY KEY,
            site_name  TEXT NOT NULL,
            latitude   REAL,
            longitude  REAL,
            region     TEXT,
            site_type  TEXT,
            vendor     TEXT,
            status     TEXT DEFAULT 'Active',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # One row per cell; cell_name is the cross-DB join key
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cells (
            cell_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cell_name       TEXT    NOT NULL UNIQUE,
            site_id         TEXT    REFERENCES sites(site_id),
            technology      TEXT,
            vendor          TEXT,
            frequency_band  TEXT,
            azimuth         REAL,
            mechanical_tilt REAL,
            electrical_tilt REAL,
            pci             INTEGER,
            status          TEXT DEFAULT 'Active',
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sectors (
            sector_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id         TEXT REFERENCES sites(site_id),
            sector_name     TEXT,
            technology      TEXT,
            frequency_band  TEXT,
            azimuth         REAL,
            mechanical_tilt REAL,
            electrical_tilt REAL,
            vendor          TEXT,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cells_site   ON cells(site_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cells_vendor ON cells(vendor)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cells_tech   ON cells(technology)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sectors_site ON sectors(site_id)')

    conn.commit()
    conn.close()
    logger.info(f'{METADATA_DB} ready.')


def _ensure_sync_log():
    conn = sqlite3.connect(APP_DB)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sync_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type     TEXT NOT NULL,
            technology    TEXT NOT NULL,
            status        TEXT NOT NULL,
            rows_affected INTEGER DEFAULT 0,
            message       TEXT,
            started_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info('sync_log ready.')


def _create_per_tech_tables():
    """
    Create five per-technology staging tables in metadata.db.
    Each table stores the exact CSV column headers from the Atoll export
    as TEXT columns, plus synthetic `technology` and `updated_at` columns.
    `cell_name` is the natural primary key used for ON CONFLICT upserts.
    """
    # Columns are exactly the CSV header names from the Atoll exports
    # (verified against 2026-02-15 snapshot).
    _PER_TECH_SCHEMAS = {
        'cells_2g': [
            'cell_name', 'site_id', 'site_name', 'vendor',
            'lat', 'long', 'cluster', 'azimuth', 'etilt', 'mtilt',
            'frequency_band', 'bcc', 'active_state',
        ],
        'cells_3g': [
            'cell_name', 'nodeb_id', 'nodeb_name', 'vendor',
            'lat', 'long', 'cluster', 'azimuth', 'etilt', 'mtilt',
            'dl_uarfcn', 'psc', 'active_state',
        ],
        'cells_4g_fdd': [
            'cell_name', 'enb_id_actual', 'enb_name', 'vendor',
            'lat', 'long', 'cluster', 'azimuth', 'etilt', 'mtilt',
            'band', 'pci', 'active_state',
        ],
        'cells_4g_tdd': [
            'cell_name', 'enb_id_actual', 'enb_name', 'vendor',
            'lat', 'long', 'cluster', 'azimuth', 'etilt', 'mtilt',
            'band', 'pci', 'active_state',
        ],
        'cells_5g': [
            'cell_name', 'gnb_id_actual', 'gnb_name', 'vendor',
            'lat', 'long', 'cluster', 'azimuth', 'etilt', 'mtilt',
            'bw', 'pci', 'active_state',
        ],
    }

    conn   = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()

    for table, csv_cols in _PER_TECH_SCHEMAS.items():
        # cell_name is PRIMARY KEY; every other CSV column is TEXT nullable;
        # technology and updated_at are synthetic (not in the raw CSV).
        col_defs = ['cell_name TEXT PRIMARY KEY']
        col_defs += [f'"{c}" TEXT' for c in csv_cols if c != 'cell_name']
        col_defs += [
            'technology TEXT',
            'updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        ]
        cursor.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})'
        )
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{table}_technology" '
            f'ON "{table}" (technology)'
        )

    conn.commit()
    conn.close()
    logger.info('Per-tech tables (cells_2g/3g/4g_fdd/4g_tdd/5g) ready.')


def run_migrations():
    _create_metadata_db()
    _create_per_tech_tables()
    _create_pm_db(NOKIA_PM_DB)
    _create_pm_db(HUAWEI_PM_DB)
    _ensure_sync_log()
    logger.info('All DB migrations complete.')
