"""
Metadata Processor
==================
Reads Atoll-exported CSV files from SFTP server 192.168.7.207 and imports
them into five per-technology tables (cells_2g, cells_3g, cells_4g_fdd,
cells_4g_tdd, cells_5g), then refreshes the legacy cells / sites tables
so the rest of the app (network map, reports, KPI queries) keeps working.

New pipeline (called by scheduler)
-----------------------------------
  run_metadata_sync(downloaded_files)
    └── _identify_tech(filename_stem)    → (table_name, technology)
    └── import_csv_to_cells(path, table, tech)
          ├── pd.read_csv(dtype=str)
          ├── keep only columns declared in _COLUMNS[table_name]
          ├── INSERT OR REPLACE into per-tech table
          └── _populate_legacy_tables(conn, table_name, technology)
                ├── INSERT OR REPLACE INTO sites  (COALESCE sname/sid)
                └── DELETE FROM cells WHERE technology=?
                    INSERT OR IGNORE INTO cells   (per _LEGACY_MAP)

Lessons applied
---------------
* Per-tech column list is `PER_TECH_CSV_SCHEMA` in `sync/db_migration.py`.
* No synthetic cell_id from CSV for legacy `cells` — legacy uses INTEGER PK AUTOINCREMENT.
* INSERT OR REPLACE (not ON CONFLICT DO UPDATE) — compatible with the Windows
  SQLite build shipped with Python 3.14.
* COALESCE(NULLIF(TRIM(sname),''), sid) — prevents NOT NULL violation on
  sites.site_name when site_name column is blank in the CSV.
* _find_col / fuzzy matching removed from the hot path — schema is explicit.

Legacy helpers
--------------
process_metadata_file()      — kept for import_local_files.py (explicit col map)
seed_pm_cells_to_metadata()  — kept for PM-→-metadata placeholder seeding
"""

import os
import re
import sys
import sqlite3
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import METADATA_DB
from sync.db_migration import PER_TECH_CSV_SCHEMA
from sync.metadata_active_sql import legacy_cells_activity_case_sql

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-tech columns: single source of truth in sync/db_migration.py
# ---------------------------------------------------------------------------

_COLUMNS = PER_TECH_CSV_SCHEMA

# Per-tech table → (site_id_col, site_name_col) in that table
_SITE_COL = {
    'cells_2g':     ('site_id',       'site_name'),
    'cells_3g':     ('nodeb_id',      'nodeb_name'),
    'cells_4g_fdd': ('enb_id_actual', 'enb_name'),
    'cells_4g_tdd': ('enb_id_actual', 'enb_name'),
    'cells_5g':     ('gnb_id_actual', 'gnb_name'),
}

# Per-tech table → mapping  legacy_cells_column → per_tech_column
_LEGACY_MAP = {
    'cells_2g': {
        'site_id': 'site_id', 'frequency_band': 'frequency_band',
        'azimuth': 'azimuth', 'mechanical_tilt': 'mtilt',
        'electrical_tilt': 'etilt', 'pci': 'bcch',
    },
    'cells_3g': {
        'site_id': 'nodeb_id', 'frequency_band': 'dl_uarfcn',
        'azimuth': 'azimuth', 'mechanical_tilt': 'mtilt',
        'electrical_tilt': 'etilt', 'pci': 'psc',
    },
    'cells_4g_fdd': {
        'site_id': 'enb_id_actual', 'frequency_band': 'band',
        'azimuth': 'azimuth', 'mechanical_tilt': 'mtilt',
        'electrical_tilt': 'etilt', 'pci': 'pci',
    },
    'cells_4g_tdd': {
        'site_id': 'enb_id_actual', 'frequency_band': 'band',
        'azimuth': 'azimuth', 'mechanical_tilt': 'mtilt',
        'electrical_tilt': 'etilt', 'pci': 'pci',
    },
    'cells_5g': {
        'site_id': 'gnb_id_actual', 'frequency_band': 'bw',
        'azimuth': 'azimuth', 'mechanical_tilt': 'mtilt',
        'electrical_tilt': 'etilt', 'pci': 'pci',
    },
}

# Technology identification patterns (checked in order — specific before generic)
_TECH_PATTERNS = [
    (r'4g.?tdd|tdd.?4g|lte.?tdd|tdd.?lte', 'cells_4g_tdd', '4G-TDD'),
    (r'4g.?fdd|fdd.?4g|lte.?fdd|fdd.?lte', 'cells_4g_fdd', '4G-FDD'),
    (r'5g\b|nr\b',                           'cells_5g',     '5G'),
    (r'3g\b|wcdma|umts',                     'cells_3g',     '3G'),
    (r'2g\b|gsm\b',                          'cells_2g',     '2G'),
    (r'4g\b|lte\b',                          'cells_4g_fdd', '4G-FDD'),  # generic fallback
]


# ---------------------------------------------------------------------------
# Technology identification
# ---------------------------------------------------------------------------

def _identify_tech(filename_stem):
    """
    Return (table_name, technology) for a filename stem, or (None, None).

    Examples:
      'meta_20260215_1200_Site 4G TDD - 2026-02-15' → ('cells_4g_tdd', '4G-TDD')
      'meta_20260215_1200_Site 3G - 2026-02-15'     → ('cells_3g',     '3G')
    """
    key = filename_stem.lower()
    for pattern, table, tech in _TECH_PATTERNS:
        if re.search(pattern, key):
            return table, tech
    return None, None


# ---------------------------------------------------------------------------
# Core import function
# ---------------------------------------------------------------------------

def import_csv_to_cells(file_path, table_name, technology):
    """
    Import one Atoll CSV file into a per-technology table, then refresh the
    legacy cells / sites tables for the network map and reports.

    Steps:
      1. Read CSV with pandas (dtype=str) — keeps all values as strings.
      2. Strip whitespace; normalise empty / nan-like values to None (→ NULL).
      3. Keep only columns declared in _COLUMNS[table_name]; warn on gaps.
      4. Add synthetic `technology` column.
      5. INSERT OR REPLACE into per-tech table (one row per cell_name).
      6. Call _populate_legacy_tables() inside the same connection.

    Returns (upserted, skipped, error_string_or_None).
    """
    schema_cols = _COLUMNS[table_name]

    try:
        df = pd.read_csv(file_path, dtype=str)
    except Exception as e:
        logger.error(f'[{table_name}] Cannot read {file_path}: {e}')
        return 0, 0, str(e)

    # Normalise column headers: lowercase + strip so 'Lat'/'LAT' matches 'lat'.
    df.columns = df.columns.str.lower().str.strip()

    # ── Normalise string values ─────────────────────────────────────────────
    # fillna('') so str.strip() never sees float NaN, then blank/nan → None.
    df = df.fillna('')
    for col in df.columns:
        df[col] = df[col].str.strip()
    df.replace(
        {'': None, 'nan': None, 'NaN': None, 'NULL': None,
         'null': None, 'N/A': None, 'n/a': None, '#N/A': None},
        inplace=True,
    )

    # ── Filter to schema columns ────────────────────────────────────────────
    present = [c for c in schema_cols if c in df.columns]
    missing = [c for c in schema_cols if c not in df.columns]
    if missing:
        logger.warning(f'[{table_name}] CSV missing schema columns: {missing}')
    if 'cell_name' not in present:
        msg = (f'[{table_name}] No cell_name column in {file_path}. '
               f'CSV columns: {list(df.columns)}')
        logger.error(msg)
        return 0, 0, msg

    df = df[present].copy()
    df['technology'] = technology

    # ── Drop rows without a cell_name ───────────────────────────────────────
    before  = len(df)
    df      = df[df['cell_name'].notna()]
    skipped = before - len(df)

    if df.empty:
        logger.warning(f'[{table_name}] No valid rows after filtering — nothing inserted.')
        return 0, skipped, None

    # ── Upsert into per-tech table ──────────────────────────────────────────
    # INSERT OR REPLACE deletes the old row and inserts the new one when
    # cell_name (PRIMARY KEY) conflicts — safe and Windows-SQLite-compatible.
    insert_cols = list(df.columns)   # schema_cols filtered to present + technology
    col_sql     = ', '.join(f'"{c}"' for c in insert_cols)
    ph_sql      = ', '.join(['?'] * len(insert_cols))
    sql = (
        f'INSERT OR REPLACE INTO "{table_name}" '
        f'({col_sql}, updated_at) '
        f'VALUES ({ph_sql}, CURRENT_TIMESTAMP)'
    )
    rows = [tuple(row) for _, row in df.iterrows()]

    conn = sqlite3.connect(METADATA_DB, timeout=30)
    try:
        conn.executemany(sql, rows)
        upserted = len(rows)
        _populate_legacy_tables(conn, table_name, technology)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f'[{table_name}] DB error during upsert: {e}')
        return 0, skipped, str(e)
    finally:
        conn.close()

    logger.info(
        f'[{table_name}/{technology}] {upserted} upserted, {skipped} skipped '
        f'(source: {os.path.basename(file_path)})'
    )
    return upserted, skipped, None


# ---------------------------------------------------------------------------
# Legacy table refresh
# ---------------------------------------------------------------------------

def _populate_legacy_tables(conn, table_name, technology):
    """
    Refresh sites and cells from a freshly loaded per-tech table.
    Must be called inside an open connection (caller commits).

    Sites:
      One row per site_id aggregated with MAX() so multiple cells sharing
      a site produce a single INSERT OR REPLACE.
      COALESCE(MAX(sname), sid) prevents the sites.site_name NOT NULL fail
      when all sname values for a site_id are blank.

    Cells:
      DELETE all rows for this technology, then INSERT OR IGNORE fresh data.
      INSERT OR IGNORE (rather than plain INSERT) silently skips any
      cell_name that already exists under a different technology — no crash.
    """
    sid_col, sname_col = _SITE_COL[table_name]
    lmap               = _LEGACY_MAP[table_name]

    # ── Sites ───────────────────────────────────────────────────────────────
    # Use ON CONFLICT DO UPDATE with COALESCE so a later tech CSV that has
    # NULL lat/long does not wipe coordinates already set by an earlier one
    # (e.g. 4G-TDD import must not erase 3G coordinates for co-located sites).
    conn.execute(f'''
        INSERT INTO sites
            (site_id, site_name, latitude, longitude, region, vendor, status, updated_at)
        SELECT
            NULLIF(TRIM("{sid_col}"),   '') ,
            COALESCE(
                MAX(NULLIF(TRIM("{sname_col}"), '')),
                NULLIF(TRIM("{sid_col}"),   '')
            ),
            CAST(MAX(lat)  AS REAL),
            CAST(MAX(long) AS REAL),
            COALESCE(
                MAX(NULLIF(TRIM(area),    '')),
                MAX(NULLIF(TRIM(cluster), ''))
            ),
            MAX(NULLIF(TRIM(vendor),  '')),
            'Active',
            CURRENT_TIMESTAMP
        FROM   "{table_name}"
        WHERE  NULLIF(TRIM("{sid_col}"), '') IS NOT NULL
        GROUP  BY NULLIF(TRIM("{sid_col}"), '')
        ON CONFLICT(site_id) DO UPDATE SET
            site_name  = COALESCE(excluded.site_name,  sites.site_name),
            latitude   = COALESCE(excluded.latitude,   sites.latitude),
            longitude  = COALESCE(excluded.longitude,  sites.longitude),
            region     = COALESCE(excluded.region,     sites.region),
            vendor     = COALESCE(excluded.vendor,     sites.vendor),
            status     = 'Active',
            updated_at = CURRENT_TIMESTAMP
    ''')

    # ── Cells ────────────────────────────────────────────────────────────────
    conn.execute('DELETE FROM cells WHERE technology = ?', (technology,))

    site_id_col  = lmap['site_id']
    freq_col     = lmap['frequency_band']
    az_col       = lmap['azimuth']
    mtilt_col    = lmap['mechanical_tilt']
    etilt_col    = lmap['electrical_tilt']
    pci_col      = lmap['pci']
    activity_case = legacy_cells_activity_case_sql(table_name)

    conn.execute(f'''
        INSERT OR IGNORE INTO cells
            (cell_name, site_id, technology, vendor, frequency_band,
             azimuth, mechanical_tilt, electrical_tilt, pci, status, updated_at)
        SELECT
            cell_name,
            NULLIF(TRIM("{site_id_col}"),  ''),
            technology,
            NULLIF(TRIM(vendor),           ''),
            NULLIF(TRIM("{freq_col}"),     ''),
            CAST(NULLIF(TRIM("{az_col}"),    '') AS REAL),
            CAST(NULLIF(TRIM("{mtilt_col}"), '') AS REAL),
            CAST(NULLIF(TRIM("{etilt_col}"), '') AS REAL),
            CAST(NULLIF(TRIM("{pci_col}"),   '') AS INTEGER),
            {activity_case},
            CURRENT_TIMESTAMP
        FROM "{table_name}"
        WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''
    ''')


# ---------------------------------------------------------------------------
# Main entry point (called by scheduler)
# ---------------------------------------------------------------------------

def run_metadata_sync(downloaded_files):
    """
    downloaded_files: {filename_stem: [local_path, ...]}

    For each file:
      1. _identify_tech(stem)  → (table_name, technology)
      2. import_csv_to_cells() → upsert per-tech + refresh legacy tables

    Returns {key: {status, upserted, skipped} or {status, error/reason}}.
    """
    summary = {}
    for key, value in downloaded_files.items():
        file_paths = [p for p in (value if isinstance(value, list) else [value]) if p]
        if not file_paths:
            summary[key] = {'status': 'skipped', 'reason': 'No files downloaded'}
            continue

        table_name, technology = _identify_tech(key)
        if table_name is None:
            logger.warning(f'Technology not recognised for "{key}" — skipping.')
            summary[key] = {'status': 'skipped', 'reason': 'Technology not recognized'}
            continue

        total_up = 0
        total_sk = 0
        last_err = None

        for fp in file_paths:
            up, sk, err = import_csv_to_cells(fp, table_name, technology)
            if err:
                last_err = err
            else:
                total_up += up
                total_sk += sk

        if last_err and total_up == 0:
            summary[key] = {'status': 'error', 'error': last_err}
        else:
            summary[key] = {'status': 'ok', 'upserted': total_up, 'skipped': total_sk}

    return summary


# ---------------------------------------------------------------------------
# PM → metadata seeder (unchanged)
# ---------------------------------------------------------------------------

def seed_pm_cells_to_metadata(pm_db_path, vendor):
    """
    For every cell_name in a PM database not yet in metadata.db,
    insert a placeholder site + cell so cross-DB JOINs work before a
    full metadata sync has run.
    """
    from sync_config import PM_TECHNOLOGIES, pm_table_name, HUAWEI_PM_DB

    def _site_id(cell_name):
        m = re.match(r'^(\d+)', cell_name)
        return m.group(1) if m else None

    def _site_name(cell_name):
        return re.sub(r'[-_][A-Za-z]\d*$', '', cell_name)

    try:
        pm_conn   = sqlite3.connect(pm_db_path)
        meta_conn = sqlite3.connect(METADATA_DB, timeout=30)

        pm_rows = []
        if os.path.abspath(pm_db_path) == os.path.abspath(HUAWEI_PM_DB):
            for tech in PM_TECHNOLOGIES:
                table = pm_table_name(tech)
                try:
                    rows = pm_conn.execute(
                        f'SELECT DISTINCT cell_name FROM "{table}" '
                        f"WHERE cell_name IS NOT NULL AND TRIM(cell_name) != ''"
                    ).fetchall()
                    for r in rows:
                        pm_rows.append((r[0], tech))
                except sqlite3.OperationalError:
                    continue
        else:
            for tech in PM_TECHNOLOGIES:
                table = pm_table_name(tech)
                try:
                    rows = pm_conn.execute(
                        f'SELECT DISTINCT cell_name FROM "{table}"'
                    ).fetchall()
                    for r in rows:
                        pm_rows.append((r[0], tech))
                except sqlite3.OperationalError:
                    continue
        pm_conn.close()

        existing_cells = {r[0] for r in meta_conn.execute('SELECT cell_name FROM cells').fetchall()}
        existing_sites = {r[0] for r in meta_conn.execute('SELECT site_id  FROM sites').fetchall()}

        seeded = 0
        for cell_name, tech in pm_rows:
            if cell_name in existing_cells:
                continue
            sid   = _site_id(cell_name)
            sname = _site_name(cell_name)
            if sid and sid not in existing_sites:
                meta_conn.execute(
                    "INSERT OR IGNORE INTO sites (site_id, site_name, vendor, status) "
                    "VALUES (?, ?, ?, 'Active')",
                    (sid, sname, vendor)
                )
                existing_sites.add(sid)
            meta_conn.execute(
                "INSERT OR IGNORE INTO cells "
                "(cell_name, site_id, technology, vendor, status) "
                "VALUES (?, ?, ?, ?, 'Active')",
                (cell_name, sid, tech, vendor)
            )
            existing_cells.add(cell_name)
            seeded += 1

        meta_conn.commit()
        meta_conn.close()
        logger.info(f'Seeded {seeded} PM cells from {pm_db_path} into {METADATA_DB}.')
        return seeded
    except Exception as e:
        logger.error(f'seed_pm_cells_to_metadata failed: {e}')
        return 0


# ---------------------------------------------------------------------------
# Explicit-column-map entry point — kept for import_local_files.py
# ---------------------------------------------------------------------------

def _load_file(file_path, nrows=None):
    ext = os.path.splitext(file_path)[1].lower()
    kw  = {'dtype': str} if nrows is None else {'dtype': str, 'nrows': nrows}
    if ext == '.csv':
        return pd.read_csv(file_path, **kw)
    try:
        return pd.read_excel(file_path, engine='openpyxl', **kw)
    except Exception:
        return pd.read_excel(file_path, engine='xlrd', **kw)


def _find_col(columns, candidates):
    col_map = {str(c).lower().strip(): c for c in columns}
    for cand in candidates:
        cand_l = cand.lower()
        if cand_l in col_map:
            return col_map[cand_l]
        for low, orig in col_map.items():
            if cand_l in low:
                return orig
    return None


def _safe_float(val):
    try:
        f = float(val)
        return None if (f != f) else f
    except (TypeError, ValueError):
        return None


def _safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return None if s in ('', 'nan', 'None') else s


_ACTIVE_VALUES   = {'activated', 'unlocked', 'cell_active',
                    'active', 'enabled', 'true', '1', 'yes'}
_INACTIVE_VALUES = {'deactivated', 'locked', 'cell_inactive',
                    'inactive', 'disabled', 'false', '0', 'no'}


def _normalize_status(raw):
    if not raw:
        return 'Active'
    val = raw.strip().lower()
    if val in _ACTIVE_VALUES:
        return 'Active'
    if val in _INACTIVE_VALUES:
        return 'Inactive'
    return raw


def _extract_site_id(site_name):
    m = re.match(r'^(\d+)', str(site_name).strip())
    return m.group(1) if m else site_name


_LTE_TDD_EARFCN_MIN = 36200
_LTE_TDD_EARFCN_MAX = 45589


def _lte_duplex(duplex_raw, earfcn_raw):
    if duplex_raw:
        val = str(duplex_raw).strip().upper()
        if 'TDD' in val:
            return '4G-TDD'
        if 'FDD' in val:
            return '4G-FDD'
    if earfcn_raw is not None:
        try:
            earfcn = float(earfcn_raw)
            if _LTE_TDD_EARFCN_MIN <= earfcn <= _LTE_TDD_EARFCN_MAX:
                return '4G-TDD'
            return '4G-FDD'
        except (TypeError, ValueError):
            pass
    # Default to FDD when duplex cannot be inferred. This keeps the UI and
    # filters consistent (we only expose 4G-FDD / 4G-TDD).
    return '4G-FDD'


def process_metadata_file(file_path, tech, col_map):
    """
    Import a single metadata CSV/XLSX using an explicit column map.
    Used by import_local_files.py.

    col_map maps DB field names → CSV column names, e.g.:
        {'cell_name': 'cell_name', 'pci': 'psc', 'latitude': 'lat', ...}

    Returns (upserted, skipped, error_string_or_None).
    """
    try:
        df = _load_file(file_path)
    except Exception as e:
        return 0, 0, str(e)

    def _csv(db_field):
        csv_col = col_map.get(db_field)
        return csv_col if csv_col in df.columns else None

    cell_col  = _csv('cell_name')
    site_id_c = _csv('site_id')
    sname_c   = _csv('site_name')
    lat_c     = _csv('latitude')
    lon_c     = _csv('longitude')
    az_c      = _csv('azimuth')
    etilt_c   = _csv('electrical_tilt')
    mtilt_c   = _csv('mechanical_tilt')
    vendor_c  = _csv('vendor')
    pci_c     = _csv('pci')
    status_c  = _csv('status')
    if not status_c and 'admin_state' in df.columns:
        status_c = 'admin_state'
    duplex_c  = _find_col(list(df.columns), ['duplex_mode', 'duplexmode',
                                              'duplex_type', 'duplextype',
                                              'fddtddind', 'duplex'])

    if not cell_col:
        return 0, 0, (f'[{tech}] cell_name column "{col_map.get("cell_name")}" '
                      f'not found. Columns: {list(df.columns)}')

    logger.info(f'[{tech}] Columns mapped — cell:{cell_col}, lat:{lat_c}, lon:{lon_c}, pci:{pci_c}')

    conn       = sqlite3.connect(METADATA_DB, timeout=30)
    cursor     = conn.cursor()
    upserted   = 0
    skipped    = 0
    sites_seen = set()

    for _, row in df.iterrows():
        cell_name = _safe_str(row.get(cell_col))
        if not cell_name:
            skipped += 1
            continue

        raw_sid   = _safe_str(row.get(site_id_c))  if site_id_c else None
        raw_sname = _safe_str(row.get(sname_c))    if sname_c   else None
        site_id   = raw_sid or (raw_sname and _extract_site_id(raw_sname)) or _extract_site_id(cell_name)
        site_name = raw_sname or site_id
        lat       = _safe_float(row.get(lat_c))    if lat_c     else None
        lon       = _safe_float(row.get(lon_c))    if lon_c     else None
        vendor    = _safe_str(row.get(vendor_c))   if vendor_c  else None
        azimuth   = _safe_float(row.get(az_c))     if az_c      else None
        etilt     = _safe_float(row.get(etilt_c))  if etilt_c   else None
        mtilt     = _safe_float(row.get(mtilt_c))  if mtilt_c   else None
        pci_raw   = _safe_float(row.get(pci_c))    if pci_c     else None
        pci_int   = int(pci_raw) if pci_raw is not None else None
        status    = _normalize_status(_safe_str(row.get(status_c)) if status_c else None)
        if tech == '4G':
            duplex_raw = _safe_str(row.get(duplex_c)) if duplex_c else None
            freq_raw   = row.get(_csv('frequency_band')) if _csv('frequency_band') else None
            cell_tech  = _lte_duplex(duplex_raw, freq_raw)
        else:
            cell_tech = tech

        if site_id and site_id not in sites_seen:
            cursor.execute('''
                INSERT INTO sites (site_id, site_name, latitude, longitude, site_type, vendor, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Active')
                ON CONFLICT(site_id) DO UPDATE SET
                    site_name  = COALESCE(excluded.site_name,  sites.site_name),
                    latitude   = COALESCE(excluded.latitude,   sites.latitude),
                    longitude  = COALESCE(excluded.longitude,  sites.longitude),
                    site_type  = COALESCE(excluded.site_type,  sites.site_type),
                    vendor     = COALESCE(excluded.vendor,     sites.vendor),
                    status     = 'Active',
                    updated_at = CURRENT_TIMESTAMP
            ''', (site_id, site_name, lat, lon, tech, vendor))
            sites_seen.add(site_id)

        cursor.execute('''
            INSERT INTO cells
                (cell_name, site_id, technology, frequency_band,
                 azimuth, mechanical_tilt, electrical_tilt, vendor, pci, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cell_name) DO UPDATE SET
                site_id         = COALESCE(excluded.site_id,         cells.site_id),
                technology      = COALESCE(excluded.technology,      cells.technology),
                frequency_band  = COALESCE(excluded.frequency_band,  cells.frequency_band),
                azimuth         = COALESCE(excluded.azimuth,         cells.azimuth),
                mechanical_tilt = COALESCE(excluded.mechanical_tilt, cells.mechanical_tilt),
                electrical_tilt = COALESCE(excluded.electrical_tilt, cells.electrical_tilt),
                vendor          = COALESCE(excluded.vendor,          cells.vendor),
                pci             = COALESCE(excluded.pci,             cells.pci),
                status          = excluded.status,
                updated_at      = CURRENT_TIMESTAMP
        ''', (cell_name, site_id, cell_tech, cell_tech, azimuth, mtilt, etilt, vendor, pci_int, status))
        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'[{tech}] process_metadata_file: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None
