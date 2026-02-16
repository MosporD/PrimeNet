"""
Metadata Processor
==================
Reads metadata files (XLSX or CSV) with lat/long, azimuth, tilt, site/cell
info and upserts into metadata.db → sites + cells tables.

The metadata server has snapshot folders; each folder contains 5 files:
  2G, 3G, 4G-FDD, 4G-TDD, 5G  (XLSX or CSV)

Nokia and Huawei sites are in the same metadata snapshot — vendor is
inferred from a 'vendor' / 'Vendor' column if present, or passed explicitly.
"""

import os
import sqlite3
import logging
import pandas as pd

logger = logging.getLogger(__name__)

METADATA_DB = 'metadata.db'


def _load_file(file_path):
    """Load a metadata file as a DataFrame; supports CSV and XLSX/XLS."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.csv':
        return pd.read_csv(file_path, dtype=str)
    # Try openpyxl first (proper .xlsx), fall back to xlrd (old .xls/.xlsx)
    try:
        return pd.read_excel(file_path, engine='openpyxl', dtype=str)
    except Exception:
        return pd.read_excel(file_path, engine='xlrd', dtype=str)


def process_metadata_file(file_path, technology, column_map, vendor=None):
    """
    Process one metadata XLSX file for a given technology.
    Upserts sites and cells into metadata.db.
    Returns (upserted, skipped, error_message).
    """
    try:
        df = _load_file(file_path)
    except Exception as e:
        logger.error(f'Failed to read metadata file {file_path}: {e}')
        return 0, 0, str(e)

    # Build rename map: {original_column_name → db_field_name}
    # column_map values are the source column names; keys are DB field names.
    reverse_map = {}
    for db_field, src_col in column_map.items():
        if src_col and src_col in df.columns and src_col != db_field:
            reverse_map[src_col] = db_field
    df = df.rename(columns=reverse_map)

    # Minimum required for a useful row
    required = ['site_id', 'site_name']
    missing = [f for f in required if f not in df.columns]
    if missing:
        msg = (f'Metadata [{technology}] missing required columns {missing} '
               f'after mapping. Found: {list(df.columns)}')
        logger.error(msg)
        return 0, 0, msg

    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()

    upserted = 0
    skipped  = 0

    for _, row in df.iterrows():
        site_id   = str(row.get('site_id',   '')).strip()
        site_name = str(row.get('site_name', '')).strip()
        if not site_id or not site_name or site_id == 'nan':
            skipped += 1
            continue

        lat = _safe_float(row.get('latitude'))
        lon = _safe_float(row.get('longitude'))

        region    = _safe_str(row.get('region'))
        site_type = _safe_str(row.get('site_type')) or technology
        row_vendor = _safe_str(row.get('vendor')) or vendor

        # Upsert site
        cursor.execute('''
            INSERT INTO sites (site_id, site_name, latitude, longitude, region, site_type, vendor, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(site_id) DO UPDATE SET
                site_name  = excluded.site_name,
                latitude   = COALESCE(excluded.latitude,  sites.latitude),
                longitude  = COALESCE(excluded.longitude, sites.longitude),
                region     = COALESCE(excluded.region,    sites.region),
                site_type  = excluded.site_type,
                vendor     = COALESCE(excluded.vendor,    sites.vendor),
                status     = 'Active',
                updated_at = CURRENT_TIMESTAMP
        ''', (site_id, site_name, lat, lon, region, site_type, row_vendor))

        # Upsert cell if cell_name is present
        cell_name = _safe_str(row.get('cell_name'))
        if cell_name:
            azimuth   = _safe_float(row.get('azimuth'))
            mech_tilt = _safe_float(row.get('mechanical_tilt'))
            elec_tilt = _safe_float(row.get('electrical_tilt'))
            freq_band = _safe_str(row.get('frequency_band'))
            pci       = _safe_int(row.get('pci'))

            cursor.execute('''
                INSERT INTO cells
                    (cell_name, site_id, technology, vendor, frequency_band,
                     azimuth, mechanical_tilt, electrical_tilt, pci, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')
                ON CONFLICT(cell_name) DO UPDATE SET
                    site_id         = excluded.site_id,
                    technology      = COALESCE(excluded.technology,      cells.technology),
                    vendor          = COALESCE(excluded.vendor,          cells.vendor),
                    frequency_band  = COALESCE(excluded.frequency_band,  cells.frequency_band),
                    azimuth         = COALESCE(excluded.azimuth,         cells.azimuth),
                    mechanical_tilt = COALESCE(excluded.mechanical_tilt, cells.mechanical_tilt),
                    electrical_tilt = COALESCE(excluded.electrical_tilt, cells.electrical_tilt),
                    pci             = COALESCE(excluded.pci,             cells.pci),
                    status          = 'Active',
                    updated_at      = CURRENT_TIMESTAMP
            ''', (cell_name, site_id, technology, row_vendor, freq_band,
                  azimuth, mech_tilt, elec_tilt, pci))

        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'Metadata [{technology}] processed: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


def run_metadata_sync(downloaded_files, column_maps):
    """
    downloaded_files can be:
      {tech: local_path}          — legacy one-file-per-tech format
      {subfolder: [local_path]}   — new format: multiple files per subfolder

    Subfolder names are matched to column_maps keys case-insensitively
    (e.g. subfolder '4G-FDD' matches key '4G-FDD').

    Returns summary dict {tech: {status, upserted, skipped} or {status, error}}.
    """
    summary = {}
    for key, value in downloaded_files.items():
        # Normalise to a list of file paths
        if isinstance(value, list):
            file_paths = [p for p in value if p]
        elif value:
            file_paths = [value]
        else:
            summary[key] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue

        if not file_paths:
            summary[key] = {'status': 'skipped', 'reason': 'No files downloaded'}
            continue

        # Match key (subfolder name or filename stem) to a technology in column_maps.
        # Sort longest-first so "4G-FDD" is tried before a bare "4G".
        # Handles: exact match, normalised match, and prefix match
        # e.g. "2G-2025-12-03" → startswith "2G"; "4G-FDD-2025-12-03" → startswith "4G-FDD".
        tech = None
        key_upper = key.upper()
        for t in sorted(column_maps.keys(), key=len, reverse=True):
            t_upper = t.upper()
            if (t_upper == key_upper
                    or t.replace('-', '').upper() == key.replace('-', '').upper()
                    or key_upper.startswith(t_upper + '-')
                    or key_upper.startswith(t_upper + '_')
                    or key_upper == t_upper):
                tech = t
                break
        if not tech:
            tech = key  # use as-is; process_metadata_file will log missing columns

        col_map = column_maps.get(tech, {})

        total_upserted = 0
        total_skipped  = 0
        last_error     = None

        for file_path in file_paths:
            if not col_map:
                summary[tech] = {'status': 'skipped', 'reason': f'No column map for {tech}'}
                continue
            upserted, skipped, error = process_metadata_file(file_path, tech, col_map)
            if error:
                last_error = error
            else:
                total_upserted += upserted
                total_skipped  += skipped

        if last_error and total_upserted == 0:
            summary[tech] = {'status': 'error', 'error': last_error}
        else:
            summary[tech] = {'status': 'ok', 'upserted': total_upserted, 'skipped': total_skipped}

    return summary


def seed_pm_cells_to_metadata(pm_db_path, vendor):
    """
    For every cell_name in a PM database that is missing from metadata.db,
    insert a placeholder site + cell row so the cross-DB JOIN works.
    Returns the number of cells seeded.
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

        existing_cells = {r[0] for r in meta_conn.execute(
            'SELECT cell_name FROM cells'
        ).fetchall()}
        existing_sites = {r[0] for r in meta_conn.execute(
            'SELECT site_id FROM sites'
        ).fetchall()}

        seeded = 0
        for cell_name, tech in pm_rows:
            if cell_name in existing_cells:
                continue
            site_id   = _site_id(cell_name)
            site_name = _site_name(cell_name)
            if site_id and site_id not in existing_sites:
                meta_conn.execute(
                    "INSERT OR IGNORE INTO sites (site_id, site_name, vendor, status) "
                    "VALUES (?, ?, ?, 'Active')",
                    (site_id, site_name, vendor)
                )
                existing_sites.add(site_id)
            meta_conn.execute(
                "INSERT OR IGNORE INTO cells (cell_name, site_id, technology, vendor, status) "
                "VALUES (?, ?, ?, ?, 'Active')",
                (cell_name, site_id, tech, vendor)
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
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val):
    try:
        f = float(val)
        return None if (f != f) else f   # NaN check
    except (TypeError, ValueError):
        return None

def _safe_int(val):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None

def _safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return None if s in ('', 'nan', 'None') else s
