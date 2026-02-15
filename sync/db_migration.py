"""
DB Migration
Adds columns and indexes needed for the SFTP sync feature.
Run once on startup (safe to re-run, uses IF NOT EXISTS).
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

DB_PATH = 'ncm_users.db'


def run_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Add mechanical_tilt to sectors if missing
    cursor.execute("PRAGMA table_info(sectors)")
    sector_cols = [row[1] for row in cursor.fetchall()]
    if 'mechanical_tilt' not in sector_cols:
        cursor.execute('ALTER TABLE sectors ADD COLUMN mechanical_tilt REAL')
        logger.info('Added mechanical_tilt column to sectors.')

    # 2. Add unique index on cell_kpis(cell_id, timestamp) for upsert support
    cursor.execute('''
        SELECT name FROM sqlite_master
        WHERE type='index' AND name='idx_cell_kpis_unique'
    ''')
    if not cursor.fetchone():
        cursor.execute('''
            CREATE UNIQUE INDEX idx_cell_kpis_unique
            ON cell_kpis (cell_id, timestamp)
        ''')
        logger.info('Created unique index on cell_kpis(cell_id, timestamp).')

    # 3. Add sync_log table to track pull history
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type   TEXT NOT NULL,   -- 'pm' or 'metadata'
            technology  TEXT NOT NULL,   -- '2G','3G','4G','5G'
            status      TEXT NOT NULL,   -- 'ok','error','skipped'
            rows_affected INTEGER DEFAULT 0,
            message     TEXT,
            started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    logger.info('sync_log table ready.')

    conn.commit()
    conn.close()
    logger.info('DB migrations complete.')
