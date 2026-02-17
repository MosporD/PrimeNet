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
from sync_config import METADATA_DB, NOKIA_PM_DB, HUAWEI_PM_DB, NCMUSERS_DB as APP_DB

logger = logging.getLogger(__name__)


_KPI_COLS = '''
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_name TEXT    NOT NULL,
    timestamp TEXT    NOT NULL
'''


def _create_pm_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS cell_kpis (
            {_KPI_COLS},
            UNIQUE (cell_name, timestamp) ON CONFLICT REPLACE
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kpis_cell_ts ON cell_kpis (cell_name, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kpis_ts       ON cell_kpis (timestamp)')
    conn.commit()
    conn.close()
    logger.info(f'{db_path} ready.')


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


def run_migrations():
    _create_metadata_db()
    _create_pm_db(NOKIA_PM_DB)
    _create_pm_db(HUAWEI_PM_DB)
    _ensure_sync_log()
    logger.info('All DB migrations complete.')
