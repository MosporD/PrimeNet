"""
Metadata Processor
Reads site metadata XLSX files (lat/long, azimuth, tilt, name, region)
and upserts into the sites and sectors tables.
"""

import sqlite3
import logging
import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = 'ncm_users.db'


def process_metadata_file(file_path, technology, column_map):
    """
    Process a metadata XLSX file for a given technology.
    Upserts site records and updates sector azimuth/tilt.
    Returns (upserted, skipped, error_message).
    """
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        logger.error(f'Failed to read metadata file {file_path}: {e}')
        return 0, 0, str(e)

    # Rename columns based on mapping
    reverse_map = {v: k for k, v in column_map.items() if v in df.columns}
    df = df.rename(columns=reverse_map)

    required = ['site_id', 'site_name', 'latitude', 'longitude']
    missing = [f for f in required if f not in df.columns]
    if missing:
        msg = f'Metadata file missing required columns (after mapping): {missing}. Found: {list(df.columns)}'
        logger.error(msg)
        return 0, 0, msg

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    upserted = 0
    skipped = 0

    for _, row in df.iterrows():
        site_id = str(row.get('site_id', '')).strip()
        site_name = str(row.get('site_name', '')).strip()
        if not site_id or not site_name:
            skipped += 1
            continue

        try:
            lat = float(row.get('latitude'))
            lon = float(row.get('longitude'))
        except (TypeError, ValueError):
            logger.warning(f'Invalid lat/lon for site {site_id}, skipping.')
            skipped += 1
            continue

        region = str(row.get('region', '')).strip() or None
        site_type = str(row.get('site_type', technology)).strip() or technology

        # Upsert site
        cursor.execute('''
            INSERT INTO sites (site_id, site_name, latitude, longitude, region, site_type, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(site_id) DO UPDATE SET
                site_name       = excluded.site_name,
                latitude        = excluded.latitude,
                longitude       = excluded.longitude,
                region          = excluded.region,
                site_type       = excluded.site_type,
                status          = 'Active'
        ''', (site_id, site_name, lat, lon, region, site_type))

        # Update azimuth and mechanical tilt on matching sectors if present
        azimuth = row.get('azimuth')
        mech_tilt = row.get('mechanical_tilt')

        if pd.notna(azimuth) or pd.notna(mech_tilt):
            updates = []
            params = []
            if pd.notna(azimuth):
                updates.append('azimuth = ?')
                params.append(float(azimuth))
            if pd.notna(mech_tilt):
                updates.append('mechanical_tilt = ?')
                params.append(float(mech_tilt))
            params.append(site_id)
            cursor.execute(
                f'UPDATE sectors SET {", ".join(updates)} WHERE site_id = ?',
                params
            )

        upserted += 1

    conn.commit()
    conn.close()

    logger.info(f'Metadata [{technology}] processed: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


def run_metadata_sync(downloaded_files, column_map):
    """
    Process all downloaded metadata files (one per technology).
    Returns summary dict.
    """
    summary = {}
    for tech, file_path in downloaded_files.items():
        if not file_path:
            summary[tech] = {'status': 'skipped', 'reason': 'Download failed or not configured'}
            continue
        upserted, skipped, error = process_metadata_file(file_path, tech, column_map)
        if error:
            summary[tech] = {'status': 'error', 'error': error}
        else:
            summary[tech] = {'status': 'ok', 'upserted': upserted, 'skipped': skipped}
    return summary
