"""
DB Migration — Three-Database Architecture
==========================================
metadata.db          → sites, cells, sectors for ALL vendors (source of truth)
nokia_pm_cells.db   → Nokia hourly KPI rows keyed by cell_name + timestamp
huawei_pm_cells.db  → Huawei PM: same hourly tables as Nokia (2G_Hourly … 5G_Hourly)

Cell linkage: cell_name is the shared key across all three DBs.
The performance API queries metadata.db and ATTACHes the relevant PM db
to do cross-db JOINs purely in SQLite.
"""

import sqlite3
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sync_config import (
    PROJECT_ROOT,
    METADATA_DB,
    NOKIA_PM_DB,
    HUAWEI_PM_DB,
    NOKIA_GROUPS_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    HUAWEI_PM_DAILY_DB,
    NOKIA_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DAILY_DB,
    NEIGHBOR_KPI_DB,
    HUAWEI_NEIGHBOR_RAW_DB,
    NCMUSERS_DB as APP_DB,
    PM_TECHNOLOGIES,
    pm_table_name,
)

logger = logging.getLogger(__name__)


def _log_db_path_report() -> None:
    targets = {
        'metadata': METADATA_DB,
        'admin': APP_DB,
        'cells_nokia_hourly': NOKIA_PM_DB,
        'cells_huawei_hourly': HUAWEI_PM_DB,
        'cells_nokia_daily': NOKIA_PM_DAILY_DB,
        'cells_huawei_daily': HUAWEI_PM_DAILY_DB,
        'groups_nokia_hourly': NOKIA_GROUPS_DB,
        'groups_huawei_hourly': HUAWEI_GROUPS_DB,
        'groups_nokia_daily': NOKIA_GROUPS_DAILY_DB,
        'groups_huawei_daily': HUAWEI_GROUPS_DAILY_DB,
        'neighbors_nokia_hourly': NEIGHBOR_KPI_DB,
        'neighbors_huawei_hourly': HUAWEI_NEIGHBOR_RAW_DB,
    }
    for label, db_path in targets.items():
        logger.debug(
            'DB path report: domain=%s exists=%s path=%s',
            label,
            os.path.isfile(db_path),
            db_path,
        )


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
        existing_cols = {r[1] for r in cursor.execute(f'PRAGMA table_info("{table}")').fetchall()}
        if 'cell_name' not in existing_cols:
            cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN cell_name TEXT')
            logger.debug('%s: added legacy column cell_name', table)
        if 'timestamp' not in existing_cols:
            cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN timestamp TEXT')
            logger.debug('%s: added legacy column timestamp', table)
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_cell_ts" ON "{table}" (cell_name, timestamp)')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_ts"      ON "{table}" (timestamp)')
    conn.commit()
    conn.close()
    logger.debug('PM DB ready: %s', db_path)


def _init_huawei_pm_db(db_path):
    """Huawei PM uses the same fixed hourly tables as Nokia PM."""
    _create_pm_db(db_path)


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


def _create_cell_groups_db(db_path):
    """Create one vendor-specific cell groups DB."""
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT NOT NULL,
            description TEXT,
            is_shared   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS group_cells (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            cell_key    TEXT NOT NULL,
            cell_name   TEXT,
            vendor      TEXT,
            technology  TEXT,
            site_id     TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE,
            UNIQUE(group_id, cell_key) ON CONFLICT REPLACE
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_groups_user ON groups(user_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_group_cells_gid ON group_cells(group_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_group_cells_vendor_tech ON group_cells(vendor, technology)')
    conn.commit()
    conn.close()


def _migrate_legacy_group_db():
    """
    Split legacy single DB (cell_groups.db) into Nokia/Huawei group DBs.
    Existing vendor DB rows are preserved.
    """
    legacy = os.path.join(PROJECT_ROOT, 'cell_groups.db')
    if not os.path.isfile(legacy):
        return

    old = sqlite3.connect(legacy)
    old.row_factory = sqlite3.Row
    try:
        groups = old.execute('SELECT id, user_id, name, description, is_shared FROM groups').fetchall()
        if not groups:
            old.close()
            return
        rows = old.execute(
            '''
            SELECT gc.group_id, gc.cell_key, gc.cell_name, gc.vendor, gc.technology, gc.site_id
            FROM group_cells gc
            '''
        ).fetchall()
    except sqlite3.OperationalError:
        old.close()
        return

    groups_by_id = {int(g['id']): dict(g) for g in groups}
    by_vendor = {'Nokia': {}, 'Huawei': {}}
    for r in rows:
        v = (r['vendor'] or '').strip()
        if v not in by_vendor:
            continue
        gid = int(r['group_id'])
        if gid not in groups_by_id:
            continue
        by_vendor[v].setdefault(gid, {'group': groups_by_id[gid], 'cells': []})
        by_vendor[v][gid]['cells'].append(r)

    for vendor, db_path in (('Nokia', NOKIA_GROUPS_DB), ('Huawei', HUAWEI_GROUPS_DB)):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for payload in by_vendor[vendor].values():
            g = payload['group']
            cur.execute(
                '''
                INSERT INTO groups (user_id, name, description, is_shared)
                VALUES (?,?,?,?)
                ''',
                (g['user_id'], g['name'], g['description'], g['is_shared']),
            )
            new_gid = cur.lastrowid
            for c in payload['cells']:
                cur.execute(
                    '''
                    INSERT OR REPLACE INTO group_cells
                    (group_id, cell_key, cell_name, vendor, technology, site_id)
                    VALUES (?,?,?,?,?,?)
                    ''',
                    (new_gid, c['cell_key'], c['cell_name'], c['vendor'], c['technology'], c['site_id']),
                )
        conn.commit()
        conn.close()
    old.close()


# Per-tech CSV columns (lowercase) — single source of truth for imports.
# cell_name first (PRIMARY KEY); importer lowercases/strips CSV headers to match.
PER_TECH_CSV_SCHEMA = {
    'cells_2g': [
        'cell_name', 'vendor', 'area', 'cluster', 'bsc', 'bsc_name', 'bts_index',
        'site_name', 'site_id', 'sector', 'cell_id', 'cell_index', 'active_state',
        'admin_state', 'frequency_band', 'bcch', 'ncc', 'bcc', 'lac', 'rac',
        'mcc', 'mnc', 'lat', 'long', 'azimuth', 'etilt', 'mtilt', 'height',
        'structure', 'last_update', 'date',
    ],
    'cells_3g': [
        'cell_name', 'vendor', 'area', 'cluster', 'rnc', 'rnc_name', 'nodeb_name',
        'nodeb_id', 'sector', 'cell_id', 'active_state', 'dl_uarfcn', 'psc',
        'lac', 'rac', 'sac', 'max_pwr', 'cpich_pwr', 'mcc', 'mnc', 'dch_users',
        'lat', 'long', 'azimuth', 'etilt', 'mtilt', 'height', 'structure',
        'last_update', 'date',
    ],
    'cells_4g_fdd': [
        'cell_name', 'vendor', 'area', 'cluster', 'enb_name', 'enb_id_actual',
        'enb_id_config', 'sector', 'cell_id', 'active_state', 'admin_state',
        'tac', 'pci', 'rsi', 'cell_radius', 'dl_bw', 'dl_earfcn', 'duplix_mode',
        'pwr_config', 'mcc', 'mnc', 'ip_address', 'throughput', 'prb', 'band',
        'cell_unique', 'capacity', 'lat', 'long', 'azimuth', 'etilt', 'mtilt',
        'height', 'structure', 'last_update', 'date',
    ],
    'cells_4g_tdd': [
        'cell_name', 'vendor', 'area', 'cluster', 'enb_name', 'enb_id_actual',
        'enb_id_config', 'sector', 'cell_id', 'active_state', 'admin_state',
        'tac', 'pci', 'rsi', 'cell_radius', 'dl_bw', 'dl_earfcn', 'duplix_mode',
        'pwr_config', 'mcc', 'mnc', 'ip_address', 'throughput', 'prb', 'band',
        'cell_unique', 'capacity', 'lat', 'long', 'azimuth', 'etilt', 'mtilt',
        'height', 'structure', 'last_update', 'date',
    ],
    'cells_5g': [
        'cell_name', 'vendor', 'area', 'cluster', 'gnb_name', 'gnb_id_actual',
        'gnb_id_config', 'sector', 'cell_id', 'active_state', 'admin_state',
        'tac', 'pci', 'rsi', 'bw', 'nrarfcn', 'duplix_mode', 'ip_address',
        'lat', 'long', 'azimuth', 'etilt', 'mtilt', 'height', 'structure',
        'last_update', 'date', 'cluster_y',
    ],
}


def ensure_per_tech_columns():
    """
    Add any missing columns to existing per-tech tables (SQLite has no DROP COLUMN
    in older versions; ALTER ADD is safe for upgrades).
    """
    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    for table, cols in PER_TECH_CSV_SCHEMA.items():
        try:
            pragma_rows = cursor.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not pragma_rows:
                continue
            existing = {row[1] for row in pragma_rows}
        except sqlite3.OperationalError:
            continue
        for c in cols:
            if c == 'cell_name':
                continue
            if c not in existing:
                cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}" TEXT')
                logger.debug('%s: added column "%s"', table, c)
        # Synthetic columns on very old DBs
        existing = {
            row[1]
            for row in cursor.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        if 'technology' not in existing:
            cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN technology TEXT')
        if 'updated_at' not in existing:
            # SQLite rejects non-constant defaults on ALTER ADD in some builds.
            cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN updated_at TIMESTAMP')
    conn.commit()
    conn.close()


def _create_per_tech_tables():
    """
    Create five per-technology staging tables in metadata.db.
    Each table stores CSV columns as TEXT, plus synthetic `technology` and
    `updated_at`. `cell_name` is the natural primary key for upserts.
    """
    # Legacy DBs may predate ``technology`` / ``updated_at``; add them before indexes.
    ensure_per_tech_columns()

    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()

    for table, csv_cols in PER_TECH_CSV_SCHEMA.items():
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
        # Network map / filters performance indexes (read-heavy paths).
        cols_available = set(csv_cols) | {'cell_name', 'technology', 'updated_at'}

        def _idx(col: str):
            if col in cols_available:
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{table}_{col}" '
                    f'ON "{table}" ({col})'
                )

        # Site identifier differs by technology table.
        if table == 'cells_2g':
            _idx('site_id')
            _idx('bcch')
            _idx('bcc')
            _idx('active_state')
            _idx('admin_state')
        elif table == 'cells_3g':
            _idx('nodeb_id')
            _idx('dl_uarfcn')
            _idx('active_state')
            _idx('admin_state')
        elif table in ('cells_4g_fdd', 'cells_4g_tdd'):
            _idx('enb_id_actual')
            _idx('band')
            _idx('pci')
            _idx('active_state')
            _idx('admin_state')
        elif table == 'cells_5g':
            _idx('gnb_id_actual')
            _idx('bw')
            _idx('pci')
            _idx('active_state')
            _idx('admin_state')

    conn.commit()
    conn.close()
    ensure_per_tech_columns()


def run_migrations():
    _create_metadata_db()
    _create_per_tech_tables()
    _create_pm_db(NOKIA_PM_DB)
    _init_huawei_pm_db(HUAWEI_PM_DB)
    _ensure_sync_log()
    _create_cell_groups_db(NOKIA_GROUPS_DB)
    _create_cell_groups_db(HUAWEI_GROUPS_DB)
    _migrate_legacy_group_db()
    _log_db_path_report()
    logger.info('All SQLite DB migrations complete.')
