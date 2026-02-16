"""
Metadata Processor
==================
Reads Atoll-exported metadata CSV files and upserts into metadata.db.

No column mapping configuration is required.  The code detects whether a
file is a Site file or a Transmitter file from its filename, then
auto-detects the relevant columns (site_name, lat/long, cell_name, azimuth,
tilt …) by scanning column names for well-known keywords.

Expected file naming (Atoll export convention):
  Site 3G - YYYY-MM-DD.csv       → site coordinates for 3G
  Site L18 - YYYY-MM-DD.csv      → site coordinates for LTE 1800 (4G)
  Transmitter 2G - YYYY-MM-DD.csv → cell/transmitter data for 2G
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

def _load_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.csv':
        return pd.read_csv(file_path, dtype=str)
    try:
        return pd.read_excel(file_path, engine='openpyxl', dtype=str)
    except Exception:
        return pd.read_excel(file_path, engine='xlrd', dtype=str)


# ---------------------------------------------------------------------------
# Column auto-detection helpers
# ---------------------------------------------------------------------------

def _find_col(columns, candidates):
    """
    Return the first column whose name (case-insensitive, stripped) matches
    any candidate exactly or contains any candidate as a substring.
    """
    col_map = {str(c).lower().strip(): c for c in columns}
    for cand in candidates:
        cand_l = cand.lower()
        # exact match first
        if cand_l in col_map:
            return col_map[cand_l]
        # substring match
        for low, orig in col_map.items():
            if cand_l in low:
                return orig
    return None


# ---------------------------------------------------------------------------
# Technology inference from filename stem
# ---------------------------------------------------------------------------

def _infer_tech(key):
    """Infer technology label from a filename stem / dict key."""
    k = key.upper()
    if '5G' in k:
        return '5G'
    if '3G' in k:
        return '3G'
    if '2G' in k:
        return '2G'
    if re.search(r'L\d+', k):
        return '4G'
    return 'unknown'


# ---------------------------------------------------------------------------
# Site file processing  (columns: Name, lat, long)
# ---------------------------------------------------------------------------

def _process_site_file(file_path, key):
    technology = _infer_tech(key)
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read site file {file_path}: {e}')
        return 0, 0, str(e)

    cols = list(df.columns)

    name_col = _find_col(cols, ['name', 'site_name', 'site name', 'sitename'])
    lat_col  = _find_col(cols, ['lat', 'latitude'])
    lon_col  = _find_col(cols, ['long', 'longitude', 'lng', 'lon'])

    if not name_col:
        msg = f'Site file [{key}]: cannot detect name column. Found: {cols}'
        logger.error(msg)
        return 0, 0, msg

    conn    = sqlite3.connect(METADATA_DB)
    cursor  = conn.cursor()
    upserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        site_name = _safe_str(row.get(name_col))
        if not site_name:
            skipped += 1
            continue

        site_id = site_name   # use name as primary key (no numeric ID in Atoll exports)
        lat = _safe_float(row.get(lat_col))  if lat_col else None
        lon = _safe_float(row.get(lon_col))  if lon_col else None

        cursor.execute('''
            INSERT INTO sites (site_id, site_name, latitude, longitude, site_type, status)
            VALUES (?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(site_id) DO UPDATE SET
                site_name  = excluded.site_name,
                latitude   = COALESCE(excluded.latitude,  sites.latitude),
                longitude  = COALESCE(excluded.longitude, sites.longitude),
                site_type  = COALESCE(excluded.site_type, sites.site_type),
                status     = 'Active',
                updated_at = CURRENT_TIMESTAMP
        ''', (site_id, site_name, lat, lon, technology))
        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'Site [{key}/{technology}]: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


# ---------------------------------------------------------------------------
# Transmitter file processing  (columns: Cell_name, Site, Lat, Long, …)
# ---------------------------------------------------------------------------

def _process_transmitter_file(file_path, key):
    technology = _infer_tech(key)
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read transmitter file {file_path}: {e}')
        return 0, 0, str(e)

    cols = list(df.columns)

    cell_col  = _find_col(cols, ['cell_name', 'cellname', 'cell name', 'trans_name', 'transname', 'name'])
    site_col  = _find_col(cols, ['site', 'site_name', 'sitename'])
    lat_col   = _find_col(cols, ['latitude', 'lat'])
    lon_col   = _find_col(cols, ['longitude', 'long', 'lng', 'lon'])
    az_col    = _find_col(cols, ['azimuth'])
    etilt_col = _find_col(cols, ['elect_tilt', 'electrical_tilt', 'etilt', 'electricaltilt'])
    mtilt_col = _find_col(cols, ['mechanical downtilt', 'mechanical_tilt', 'mtilt', 'mechanicaltilt'])

    if not cell_col:
        msg = f'Transmitter file [{key}]: cannot detect cell_name column. Found: {cols}'
        logger.error(msg)
        return 0, 0, msg

    conn    = sqlite3.connect(METADATA_DB)
    cursor  = conn.cursor()
    upserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        cell_name = _safe_str(row.get(cell_col))
        if not cell_name:
            skipped += 1
            continue

        # Resolve site_id: use site_name value (same convention as Site files)
        site_name = _safe_str(row.get(site_col)) if site_col else None
        site_id   = site_name  # may be None if site column missing

        lat     = _safe_float(row.get(lat_col))   if lat_col   else None
        lon     = _safe_float(row.get(lon_col))   if lon_col   else None
        azimuth = _safe_float(row.get(az_col))    if az_col    else None
        etilt   = _safe_float(row.get(etilt_col)) if etilt_col else None
        mtilt   = _safe_float(row.get(mtilt_col)) if mtilt_col else None

        # Ensure the parent site exists (insert placeholder if not yet imported)
        if site_id:
            cursor.execute('''
                INSERT OR IGNORE INTO sites (site_id, site_name, status)
                VALUES (?, ?, 'Active')
            ''', (site_id, site_name))

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
        ''', (cell_name, site_id, technology, technology,
              azimuth, mtilt, etilt))
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
    downloaded_files: {filename_stem: [local_path, ...]}  (from download_all_xlsx_from_subfolders)
    column_maps: ignored — auto-detection used instead.

    Dispatches each file to _process_site_file or _process_transmitter_file
    based on the filename stem.

    Returns summary dict {key: {status, upserted, skipped} or {status, error}}.
    """
    summary = {}
    for key, value in downloaded_files.items():
        file_paths = [p for p in (value if isinstance(value, list) else [value]) if p]
        if not file_paths:
            summary[key] = {'status': 'skipped', 'reason': 'No files downloaded'}
            continue

        key_lower = key.lower()
        is_transmitter = 'transmitter' in key_lower

        total_up  = 0
        total_sk  = 0
        last_err  = None

        for fp in file_paths:
            if is_transmitter:
                up, sk, err = _process_transmitter_file(fp, key)
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
# PM → metadata seeder (unchanged)
# ---------------------------------------------------------------------------

def seed_pm_cells_to_metadata(pm_db_path, vendor):
    """
    For every cell_name in a PM database that is missing from metadata.db,
    insert a placeholder site + cell row so the cross-DB JOIN works.
    """
    import re

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
        existing_sites = {r[0] for r in meta_conn.execute('SELECT site_id FROM sites').fetchall()}

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
                "INSERT OR IGNORE INTO cells (cell_name, site_id, technology, vendor, status) "
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
# Safe type helpers
# ---------------------------------------------------------------------------

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
