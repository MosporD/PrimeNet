"""
Metadata Processor
==================
Reads Atoll-exported metadata CSV files and upserts into metadata.db.

Auto-detects file type from column headers:

  • If file has an 'azimuth' column → CELL FILE
    Every row is one cell.  Each row upserts:
      - a site  (site_id / site_name / lat / long / vendor)
      - a cell  (cell_name / site_id / azimuth / tilt / technology)

  • Otherwise → SITE-COORDINATE FILE
    Rows contain only site identity and location; only sites are upserted.

  • If the filename stem contains 'transmitter' → legacy transmitter path.

No column mapping configuration is needed — column names are matched by
scanning for well-known keywords (case-insensitive, substring-ok).
"""

import os
import re
import sys
import sqlite3
import logging
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import METADATA_DB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File reader
# ---------------------------------------------------------------------------

def _load_file(file_path, nrows=None):
    ext = os.path.splitext(file_path)[1].lower()
    kw = {'dtype': str} if nrows is None else {'dtype': str, 'nrows': nrows}
    if ext == '.csv':
        return pd.read_csv(file_path, **kw)
    try:
        return pd.read_excel(file_path, engine='openpyxl', **kw)
    except Exception:
        return pd.read_excel(file_path, engine='xlrd', **kw)


# ---------------------------------------------------------------------------
# Column auto-detection
# ---------------------------------------------------------------------------

def _find_col(columns, candidates):
    """
    Return the first column whose name (case-insensitive, stripped) matches
    any candidate exactly, or contains a candidate as a substring.
    """
    col_map = {str(c).lower().strip(): c for c in columns}
    for cand in candidates:
        cand_l = cand.lower()
        if cand_l in col_map:
            return col_map[cand_l]
        for low, orig in col_map.items():
            if cand_l in low:
                return orig
    return None


# ---------------------------------------------------------------------------
# Technology inference from filename stem
# ---------------------------------------------------------------------------

def _infer_tech(key):
    k = key.upper()
    if '5G' in k:
        return '5G'
    if '3G' in k:
        return '3G'
    if '2G' in k:
        return '2G'
    # LTE bands: L18, L21, L35, L9, 4G-FDD, 4G-TDD …
    if '4G-FDD' in k or 'FDD' in k:
        return '4G-FDD'
    if '4G-TDD' in k or 'TDD' in k:
        return '4G-TDD'
    if re.search(r'L\d+', k) or '4G' in k or 'LTE' in k:
        return '4G'
    return 'unknown'


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _extract_site_id(site_name):
    """
    '601-North_Jordan_Cement_Factory' → '601'
    Falls back to the full name if no numeric prefix found.
    """
    m = re.match(r'^(\d+)', str(site_name).strip())
    return m.group(1) if m else site_name


def _safe_float(val):
    try:
        f = float(val)
        return None if (f != f) else f   # filter NaN
    except (TypeError, ValueError):
        return None


def _safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return None if s in ('', 'nan', 'None') else s


# ---------------------------------------------------------------------------
# Auto-detect: does this file contain cell-level data?
# ---------------------------------------------------------------------------

def _has_cell_data(file_path):
    """
    Peek at the column headers.  Returns True when an 'azimuth' column is
    present — the definitive indicator that each row represents a cell/sector.
    """
    try:
        df = _load_file(file_path, nrows=0)
        cols = [str(c).lower().strip() for c in df.columns]
        return any('azimuth' in c for c in cols)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CELL FILE processing
# Every row → upsert one site  +  upsert one cell
# ---------------------------------------------------------------------------

def _process_cell_file(file_path, key):
    """
    Process a cell/sector export (one row = one cell).

    Columns detected (all optional except cell_name):
      cell_name  – explicit 'cell_name'/'cellname' or falls back to 'name'
      site_id    – 'site_id', 'enb_id_actual', 'enb_id'
      site_name  – 'site_name', 'site name', 'site', 'enb_name'
      lat        – 'lat', 'latitude'
      long       – 'long', 'longitude', 'lng', 'lon'
      azimuth    – 'azimuth'
      etilt      – 'elect_tilt', 'electrical_tilt', 'etilt'
      mtilt      – 'mechanical downtilt', 'mechanical_tilt', 'mtilt'
      vendor     – 'vendor'
    """
    technology = _infer_tech(key)
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read cell file {file_path}: {e}')
        return 0, 0, str(e)

    cols = list(df.columns)

    cell_name_col = (
        _find_col(cols, ['cell_name', 'cellname', 'cell name',
                         'trans_name', 'transname'])
        or _find_col(cols, ['name'])
    )
    site_id_col   = _find_col(cols, ['site_id', 'site id', 'enb_id_actual', 'enb_id'])
    site_name_col = _find_col(cols, ['site_name', 'site name', 'sitename',
                                     'site', 'enb_name'])
    lat_col       = _find_col(cols, ['lat', 'latitude'])
    lon_col       = _find_col(cols, ['long', 'longitude', 'lng', 'lon'])
    az_col        = _find_col(cols, ['azimuth'])
    etilt_col     = _find_col(cols, ['elect_tilt', 'electrical_tilt', 'etilt',
                                      'electricaltilt'])
    mtilt_col     = _find_col(cols, ['mechanical downtilt', 'mechanical_tilt',
                                      'mtilt', 'mechanicaltilt'])
    vendor_col    = _find_col(cols, ['vendor'])

    if not cell_name_col:
        msg = f'Cell file [{key}]: cannot detect cell name column. Columns: {cols}'
        logger.error(msg)
        return 0, 0, msg

    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    sites_seen = set()
    cells_up   = 0
    skipped    = 0

    for _, row in df.iterrows():
        cell_name = _safe_str(row.get(cell_name_col))
        if not cell_name:
            skipped += 1
            continue

        # ── Resolve site ──────────────────────────────────────────────────
        raw_sid   = _safe_str(row.get(site_id_col))   if site_id_col   else None
        raw_sname = _safe_str(row.get(site_name_col)) if site_name_col else None

        if raw_sid:
            site_id = raw_sid
        elif raw_sname:
            site_id = _extract_site_id(raw_sname)
        else:
            site_id = _extract_site_id(cell_name)

        site_name = raw_sname or site_id
        lat    = _safe_float(row.get(lat_col))   if lat_col    else None
        lon    = _safe_float(row.get(lon_col))   if lon_col    else None
        vendor = _safe_str(row.get(vendor_col))  if vendor_col else None

        # ── Upsert site (deduplicated per file) ───────────────────────────
        if site_id and site_id not in sites_seen:
            cursor.execute('''
                INSERT INTO sites
                    (site_id, site_name, latitude, longitude, site_type, vendor, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Active')
                ON CONFLICT(site_id) DO UPDATE SET
                    site_name  = COALESCE(excluded.site_name,  sites.site_name),
                    latitude   = COALESCE(excluded.latitude,   sites.latitude),
                    longitude  = COALESCE(excluded.longitude,  sites.longitude),
                    site_type  = COALESCE(excluded.site_type,  sites.site_type),
                    vendor     = COALESCE(excluded.vendor,     sites.vendor),
                    status     = 'Active',
                    updated_at = CURRENT_TIMESTAMP
            ''', (site_id, site_name, lat, lon, technology, vendor))
            sites_seen.add(site_id)

        # ── Upsert cell ───────────────────────────────────────────────────
        azimuth = _safe_float(row.get(az_col))    if az_col    else None
        etilt   = _safe_float(row.get(etilt_col)) if etilt_col else None
        mtilt   = _safe_float(row.get(mtilt_col)) if mtilt_col else None

        cursor.execute('''
            INSERT INTO cells
                (cell_name, site_id, technology, frequency_band,
                 azimuth, mechanical_tilt, electrical_tilt, vendor, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(cell_name) DO UPDATE SET
                site_id         = COALESCE(excluded.site_id,         cells.site_id),
                technology      = COALESCE(excluded.technology,      cells.technology),
                frequency_band  = COALESCE(excluded.frequency_band,  cells.frequency_band),
                azimuth         = COALESCE(excluded.azimuth,         cells.azimuth),
                mechanical_tilt = COALESCE(excluded.mechanical_tilt, cells.mechanical_tilt),
                electrical_tilt = COALESCE(excluded.electrical_tilt, cells.electrical_tilt),
                vendor          = COALESCE(excluded.vendor,          cells.vendor),
                status          = 'Active',
                updated_at      = CURRENT_TIMESTAMP
        ''', (cell_name, site_id, technology, technology, azimuth, mtilt, etilt, vendor))
        cells_up += 1

    conn.commit()
    conn.close()
    logger.info(
        f'Cell file [{key}/{technology}]: {cells_up} cells upserted, '
        f'{len(sites_seen)} sites upserted, {skipped} skipped.'
    )
    return cells_up, skipped, None


# ---------------------------------------------------------------------------
# SITE-COORDINATE FILE processing  (Name / lat / long only)
# ---------------------------------------------------------------------------

def _process_site_file(file_path, key):
    """
    Process a site-coordinate-only file (no per-cell antenna data).
    Populates only the sites table.
    """
    technology = _infer_tech(key)
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read site file {file_path}: {e}')
        return 0, 0, str(e)

    cols = list(df.columns)

    site_id_col  = _find_col(cols, ['enb_id_actual', 'site_id', 'site id', 'enb_id'])
    name_col     = _find_col(cols, ['enb_name', 'name', 'site_name', 'site name', 'sitename'])
    lat_col      = _find_col(cols, ['lat', 'latitude'])
    lon_col      = _find_col(cols, ['long', 'longitude', 'lng', 'lon'])
    vendor_col   = _find_col(cols, ['vendor'])

    if not name_col:
        msg = f'Site file [{key}]: cannot detect name column. Columns: {cols}'
        logger.error(msg)
        return 0, 0, msg

    conn     = sqlite3.connect(METADATA_DB)
    cursor   = conn.cursor()
    upserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        site_name = _safe_str(row.get(name_col))
        if not site_name:
            skipped += 1
            continue

        site_id = (
            _safe_str(row.get(site_id_col)) or _extract_site_id(site_name)
            if site_id_col else _extract_site_id(site_name)
        )
        lat    = _safe_float(row.get(lat_col))   if lat_col    else None
        lon    = _safe_float(row.get(lon_col))   if lon_col    else None
        vendor = _safe_str(row.get(vendor_col))  if vendor_col else None

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
        ''', (site_id, site_name, lat, lon, technology, vendor))
        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'Site [{key}/{technology}]: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


# ---------------------------------------------------------------------------
# TRANSMITTER FILE processing  (legacy — filename contains 'transmitter')
# ---------------------------------------------------------------------------

def _process_transmitter_file(file_path, key):
    technology = _infer_tech(key)
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read transmitter file {file_path}: {e}')
        return 0, 0, str(e)

    cols = list(df.columns)

    cell_col  = _find_col(cols, ['cell_name', 'cellname', 'cell name',
                                  'trans_name', 'transname', 'name'])
    site_col  = _find_col(cols, ['site', 'site_name', 'sitename'])
    lat_col   = _find_col(cols, ['latitude', 'lat'])
    lon_col   = _find_col(cols, ['longitude', 'long', 'lng', 'lon'])
    az_col    = _find_col(cols, ['azimuth'])
    etilt_col = _find_col(cols, ['elect_tilt', 'electrical_tilt', 'etilt', 'electricaltilt'])
    mtilt_col = _find_col(cols, ['mechanical downtilt', 'mechanical_tilt',
                                  'mtilt', 'mechanicaltilt'])

    if not cell_col:
        msg = f'Transmitter file [{key}]: cannot detect cell_name column. Columns: {cols}'
        logger.error(msg)
        return 0, 0, msg

    conn     = sqlite3.connect(METADATA_DB)
    cursor   = conn.cursor()
    upserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        cell_name = _safe_str(row.get(cell_col))
        if not cell_name:
            skipped += 1
            continue

        site_name = _safe_str(row.get(site_col)) if site_col else None
        site_id   = _extract_site_id(site_name) if site_name else _extract_site_id(cell_name)
        lat       = _safe_float(row.get(lat_col))   if lat_col   else None
        lon       = _safe_float(row.get(lon_col))   if lon_col   else None
        azimuth   = _safe_float(row.get(az_col))    if az_col    else None
        etilt     = _safe_float(row.get(etilt_col)) if etilt_col else None
        mtilt     = _safe_float(row.get(mtilt_col)) if mtilt_col else None

        if site_id:
            cursor.execute('''
                INSERT OR IGNORE INTO sites (site_id, site_name, status)
                VALUES (?, ?, 'Active')
            ''', (site_id, site_name or site_id))

        cursor.execute('''
            INSERT INTO cells
                (cell_name, site_id, technology, frequency_band,
                 azimuth, mechanical_tilt, electrical_tilt, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(cell_name) DO UPDATE SET
                site_id         = COALESCE(excluded.site_id,         cells.site_id),
                technology      = COALESCE(excluded.technology,      cells.technology),
                azimuth         = COALESCE(excluded.azimuth,         cells.azimuth),
                mechanical_tilt = COALESCE(excluded.mechanical_tilt, cells.mechanical_tilt),
                electrical_tilt = COALESCE(excluded.electrical_tilt, cells.electrical_tilt),
                status          = 'Active',
                updated_at      = CURRENT_TIMESTAMP
        ''', (cell_name, site_id, technology, technology, azimuth, mtilt, etilt))
        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'Transmitter [{key}/{technology}]: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_metadata_sync(downloaded_files, column_maps=None):
    """
    downloaded_files: {filename_stem: [local_path, ...]}

    Routing per file:
      • stem contains 'transmitter'  → _process_transmitter_file  (legacy)
      • file has an 'azimuth' column → _process_cell_file          (auto-detected)
      • otherwise                    → _process_site_file          (coordinates only)

    Returns {key: {status, upserted, skipped}  or  {status, error}}.
    """
    summary = {}
    for key, value in downloaded_files.items():
        file_paths = [p for p in (value if isinstance(value, list) else [value]) if p]
        if not file_paths:
            summary[key] = {'status': 'skipped', 'reason': 'No files downloaded'}
            continue

        key_lower = key.lower()
        total_up  = 0
        total_sk  = 0
        last_err  = None

        for fp in file_paths:
            if 'transmitter' in key_lower:
                up, sk, err = _process_transmitter_file(fp, key)
            elif _has_cell_data(fp):
                up, sk, err = _process_cell_file(fp, key)
            else:
                up, sk, err = _process_site_file(fp, key)

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
# PM → metadata seeder
# ---------------------------------------------------------------------------

def seed_pm_cells_to_metadata(pm_db_path, vendor):
    """
    For every cell_name in a PM database that is not yet in metadata.db,
    insert a placeholder site + cell so cross-DB JOINs work even before a
    full metadata sync has run.
    """
    def _site_id(cell_name):
        m = re.match(r'^(\d+)', cell_name)
        return m.group(1) if m else None

    def _site_name(cell_name):
        return re.sub(r'[-_][A-Za-z]\d*$', '', cell_name)

    try:
        pm_conn   = sqlite3.connect(pm_db_path)
        meta_conn = sqlite3.connect(METADATA_DB)

        pm_rows = pm_conn.execute(
            'SELECT DISTINCT cell_name, technology FROM cell_kpis'
        ).fetchall()
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
