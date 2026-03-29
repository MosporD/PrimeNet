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


# Canonical values used across all vendors / technologies:
#   Huawei  → Activated / Deactivated
#   Nokia   → Unlocked  / Locked
#   4G-TDD  → CELL_ACTIVE / CELL_INACTIVE
_ACTIVE_VALUES   = {'activated', 'unlocked', 'cell_active',
                    'active', 'enabled', 'true', '1', 'yes'}
_INACTIVE_VALUES = {'deactivated', 'locked', 'cell_inactive',
                    'inactive', 'disabled', 'false', '0', 'no'}

def _normalize_status(raw):
    """Map vendor-specific active-state values to canonical 'Active'/'Inactive'."""
    if not raw:
        return 'Active'
    val = raw.strip().lower()
    if val in _ACTIVE_VALUES:
        return 'Active'
    if val in _INACTIVE_VALUES:
        return 'Inactive'
    return raw   # preserve any unknown value as-is


# LTE TDD EARFCN range (bands 33–46: 36200–45589).
# Anything outside this range is treated as FDD.
_LTE_TDD_EARFCN_MIN = 36200
_LTE_TDD_EARFCN_MAX = 45589


def _lte_duplex(duplex_raw, earfcn_raw):
    """
    Return '4G-FDD' or '4G-TDD' for a single LTE cell.
    Tries the duplex column first; falls back to EARFCN range.
    Returns '4G' when neither source is available.
    """
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
    return '4G'


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
    # site_id candidates — cover all vendor/technology naming conventions:
    #   2G : site_id          (Atoll 2G export)
    #   3G : nodeb_id         (Atoll 3G export)
    #   4G : enb_id_actual    (Atoll 4G FDD/TDD export)
    #   5G : gnb_id_actual    (Atoll 5G export)
    site_id_col   = _find_col(cols, ['site_id', 'site id',
                                      'enb_id_actual', 'enb_id',
                                      'gnb_id_actual', 'gnb_id',
                                      'nodeb_id'])
    # site_name candidates — cover all vendor/technology naming conventions:
    #   2G : site_name        (Atoll 2G export)
    #   3G : nodeb_name       (Atoll 3G export)
    #   4G : enb_name         (Atoll 4G FDD/TDD export)
    #   5G : gnb_name         (Atoll 5G export)
    site_name_col = _find_col(cols, ['site_name', 'site name', 'sitename',
                                      'enb_name', 'gnb_name', 'nodeb_name',
                                      'site'])
    lat_col       = _find_col(cols, ['lat', 'latitude'])
    lon_col       = _find_col(cols, ['long', 'longitude', 'lng', 'lon'])
    az_col        = _find_col(cols, ['azimuth'])
    etilt_col     = _find_col(cols, ['elect_tilt', 'electrical_tilt', 'etilt',
                                      'electricaltilt'])
    mtilt_col     = _find_col(cols, ['mechanical downtilt', 'mechanical_tilt',
                                      'mtilt', 'mechanicaltilt'])
    vendor_col    = _find_col(cols, ['vendor'])
    # Frequency band / channel — actual value differs per technology:
    #   2G : frequency_band  (e.g. 'GSM900')
    #   3G : dl_uarfcn       (e.g. 10562)
    #   4G : band            (e.g. 'B7', 'B3')
    #   5G : bw              (bandwidth, e.g. 100)
    freq_col      = _find_col(cols, ['frequency_band', 'band', 'dl_uarfcn',
                                      'uarfcn', 'earfcn', 'nrarfcn', 'bw',
                                      'freq', 'arfcn'])
    # PSC (3G Primary Scrambling Code), PCI (4G Physical Cell ID), BCC/BCCH (2G)
    pci_col       = _find_col(cols, ['psc', 'scrambling_code', 'scrambling code',
                                      'primary scrambling code', 'pci',
                                      'bcc', 'bcch'])
    # Cell active state — Huawei: 'active_state', Nokia 2G: 'admin_state'
    status_col    = _find_col(cols, ['active_state', 'admin_state', 'cell_status', 'status', 'state'])
    # Duplex mode — used to split a generic '4G' file into '4G-FDD' / '4G-TDD' per row
    duplex_col    = _find_col(cols, ['duplex_mode', 'duplexmode', 'duplex_type',
                                      'duplextype', 'fddtddind', 'duplex'])

    if not cell_name_col:
        msg = f'Cell file [{key}]: cannot detect cell name column. Columns: {cols}'
        logger.error(msg)
        return 0, 0, msg

    logger.info(f'Cell file [{key}/{_infer_tech(key)}]: using column "{cell_name_col}" as cell name')
    if pci_col:
        logger.info(f'Cell file [{key}/{_infer_tech(key)}]: using column "{pci_col}" as PSC/PCI/BCCH')
    else:
        logger.warning(f'Cell file [{key}/{_infer_tech(key)}]: no PSC/PCI/BCCH column detected — pci will be NULL. '
                       f'Columns available: {cols}')

    # Warn early if the chosen column has many duplicates
    total_rows   = len(df)
    unique_names = df[cell_name_col].dropna().nunique()
    if total_rows > 0 and unique_names < total_rows * 0.7:
        logger.warning(
            f'Cell file [{key}]: only {unique_names} unique values in '
            f'"{cell_name_col}" out of {total_rows} rows. '
            f'This column may not be the per-cell identifier — check your export.'
        )

    conn = sqlite3.connect(METADATA_DB)
    cursor = conn.cursor()
    sites_seen = set()
    skipped    = 0

    before_count = conn.execute(
        "SELECT COUNT(*) FROM cells WHERE technology=?", (_infer_tech(key),)
    ).fetchone()[0]

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
        azimuth   = _safe_float(row.get(az_col))    if az_col    else None
        etilt     = _safe_float(row.get(etilt_col)) if etilt_col else None
        mtilt     = _safe_float(row.get(mtilt_col)) if mtilt_col else None
        pci       = _safe_float(row.get(pci_col))   if pci_col   else None
        pci_int   = int(pci) if pci is not None else None
        # Use the actual band/channel value from the CSV; fall back to technology label
        freq_val  = _safe_str(row.get(freq_col)) if freq_col else None
        freq_band = freq_val or technology
        # For generic '4G' files that mix FDD and TDD cells, resolve per row
        if technology == '4G':
            duplex_raw = _safe_str(row.get(duplex_col)) if duplex_col else None
            cell_tech  = _lte_duplex(duplex_raw, row.get(freq_col) if freq_col else None)
        else:
            cell_tech = technology
        # Use active_state from source if available, otherwise default to 'Active'
        status = _normalize_status(_safe_str(row.get(status_col)) if status_col else None)

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
        ''', (cell_name, site_id, cell_tech, freq_band, azimuth, mtilt, etilt, vendor, pci_int, status))

    after_count = conn.execute(
        "SELECT COUNT(*) FROM cells WHERE technology=?", (technology,)
    ).fetchone()[0]
    new_inserts = after_count - before_count

    conn.commit()
    conn.close()
    logger.info(
        f'Cell file [{key}/{technology}]: {new_inserts} new cells, '
        f'{unique_names - new_inserts} updated, '
        f'{len(sites_seen)} sites upserted, {skipped} skipped. '
        f'(file had {total_rows} rows, {unique_names} unique names in "{cell_name_col}")'
    )
    return new_inserts, skipped, None


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

    site_id_col  = _find_col(cols, ['site_id', 'site id',
                                      'enb_id_actual', 'enb_id',
                                      'gnb_id_actual', 'gnb_id',
                                      'nodeb_id'])
    name_col     = _find_col(cols, ['site_name', 'site name', 'sitename',
                                     'enb_name', 'gnb_name', 'nodeb_name',
                                     'name'])
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
    pci_col    = _find_col(cols, ['psc', 'scrambling_code', 'scrambling code',
                                   'primary scrambling code', 'pci', 'bcc', 'bcch'])
    status_col = _find_col(cols, ['active_state', 'admin_state', 'cell_status', 'status', 'state'])

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
        lat       = _safe_float(row.get(lat_col))   if lat_col    else None
        lon       = _safe_float(row.get(lon_col))   if lon_col    else None
        azimuth   = _safe_float(row.get(az_col))    if az_col     else None
        etilt     = _safe_float(row.get(etilt_col)) if etilt_col  else None
        mtilt     = _safe_float(row.get(mtilt_col)) if mtilt_col  else None
        pci_raw   = _safe_float(row.get(pci_col))   if pci_col    else None
        pci_int   = int(pci_raw) if pci_raw is not None else None
        status = _normalize_status(_safe_str(row.get(status_col)) if status_col else None)

        if site_id:
            cursor.execute('''
                INSERT OR IGNORE INTO sites (site_id, site_name, status)
                VALUES (?, ?, 'Active')
            ''', (site_id, site_name or site_id))

        cursor.execute('''
            INSERT INTO cells
                (cell_name, site_id, technology, frequency_band,
                 azimuth, mechanical_tilt, electrical_tilt, pci, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cell_name) DO UPDATE SET
                site_id         = COALESCE(excluded.site_id,         cells.site_id),
                technology      = COALESCE(excluded.technology,      cells.technology),
                azimuth         = COALESCE(excluded.azimuth,         cells.azimuth),
                mechanical_tilt = COALESCE(excluded.mechanical_tilt, cells.mechanical_tilt),
                electrical_tilt = COALESCE(excluded.electrical_tilt, cells.electrical_tilt),
                pci             = COALESCE(excluded.pci,             cells.pci),
                status          = excluded.status,
                updated_at      = CURRENT_TIMESTAMP
        ''', (cell_name, site_id, technology, technology, azimuth, mtilt, etilt, pci_int, status))
        upserted += 1

    conn.commit()
    conn.close()
    logger.info(f'Transmitter [{key}/{technology}]: {upserted} upserted, {skipped} skipped.')
    return upserted, skipped, None


# ---------------------------------------------------------------------------
# Explicit-column-map entry point  (used by import_local_files.py)
# ---------------------------------------------------------------------------

def process_metadata_file(file_path, tech, col_map):
    """
    Import a single metadata CSV/XLSX using an explicit column map.

    col_map maps DB field names → CSV column names, e.g.:
        {'cell_name': 'cell_name', 'pci': 'psc', 'latitude': 'lat', ...}

    Returns (upserted, skipped, error_string_or_None).
    """
    try:
        df = _load_file(file_path)
    except Exception as e:
        return 0, 0, str(e)

    # Reverse map: csv_col → db_field
    rev = {v: k for k, v in col_map.items()}

    def _csv(db_field):
        """Return the CSV column name for a DB field, or None if not mapped."""
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
    # Nokia 2G uses 'admin_state' instead of 'active_state'
    if not status_c and 'admin_state' in df.columns:
        status_c = 'admin_state'
    # Duplex mode — resolves generic '4G' rows to '4G-FDD' / '4G-TDD'
    duplex_c  = _find_col(list(df.columns), ['duplex_mode', 'duplexmode',
                                              'duplex_type', 'duplextype',
                                              'fddtddind', 'duplex'])

    if not cell_col:
        return 0, 0, f'[{tech}] cell_name column "{col_map.get("cell_name")}" not found in file. Columns: {list(df.columns)}'

    logger.info(f'[{tech}] Columns mapped — cell:{cell_col}, lat:{lat_c}, lon:{lon_c}, pci:{pci_c}')

    conn     = sqlite3.connect(METADATA_DB)
    cursor   = conn.cursor()
    upserted = 0
    skipped  = 0
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
        # Resolve per-row FDD/TDD for mixed '4G' files
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

    Scans all per-technology tables (2G_Hourly, 3G_Hourly, etc.).
    """
    from sync_config import PM_TECHNOLOGIES, pm_table_name

    def _site_id(cell_name):
        m = re.match(r'^(\d+)', cell_name)
        return m.group(1) if m else None

    def _site_name(cell_name):
        return re.sub(r'[-_][A-Za-z]\d*$', '', cell_name)

    try:
        pm_conn   = sqlite3.connect(pm_db_path)
        meta_conn = sqlite3.connect(METADATA_DB)

        # Collect cell_name + technology from all per-tech tables
        pm_rows = []
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
