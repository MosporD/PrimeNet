"""
Metadata Processor
==================
Reads metadata XLSX files (lat/long, azimuth, tilt, site/cell info)
and upserts into metadata.db → sites + cells tables.

The metadata server has snapshot folders; each folder contains 5 Excel files:
  2G, 3G, 4G-FDD, 4G-TDD, 5G

Nokia and Huawei sites are in the same metadata snapshot — vendor is
inferred from a 'Vendor' column if present, or passed explicitly.
"""

import sqlite3
import logging
import pandas as pd

logger = logging.getLogger(__name__)

METADATA_DB = 'metadata.db'


def process_metadata_file(file_path, technology, column_map, vendor=None):
    """
    Process one metadata XLSX file for a given technology.
    Upserts sites and cells into metadata.db.
    Returns (upserted, skipped, error_message).
    """
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to read metadata file {file_path}: {e}')
        return 0, 0, str(e)

    # Rename columns using map
    reverse_map = {v: k for k, v in column_map.items() if v in df.columns}
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


def run_metadata_sync(downloaded_files, column_map):
    """
    downloaded_files = {technology: local_path or None}
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        upserted, skipped, error = process_metadata_file(file_path, tech, column_map)
        summary[tech] = {'status': 'error', 'error': error} if error else {
            'status': 'ok', 'upserted': upserted, 'skipped': skipped
        }
    return summary


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
