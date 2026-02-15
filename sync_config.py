"""
SFTP Sync Configuration
=======================
Three data sources:
  Server 1A — Nokia PM    (10.119.219.77)
  Server 1B — Huawei PM   (10.119.10.104)
  Server 2  — Metadata    (192.168.7.207)

PM column maps only specify how to identify cell_name and timestamp in each
file.  All remaining columns are stored as-is using the original header name.
"""

# ============================================================
# SERVER 1A — Nokia PM
# 4 separate technology folders; each contains multiple XLSX
# files — the scheduler downloads the LATEST one per folder.
# ============================================================
NOKIA_PM_SERVER = {
    'host':     '10.119.219.77',
    'port':     22,
    'username': 'ftpuser',
    'password': 'Changeme_1234',
    'dirs': {
        '2G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/2G',
        '3G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/3G',
        '4G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/4G',
        '5G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/5G',
    }
}

# Only cell_name and timestamp need to be identified per technology.
# All other columns are stored as-is using the original header names.
# ⚠ Update these if the actual file headers differ.
NOKIA_PM_COLUMN_MAPS = {
    '2G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
    '3G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
    '4G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
    '5G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
}


# ============================================================
# SERVER 1B — Huawei PM
# Single folder containing one XLSX file; the scheduler
# downloads the LATEST file in that folder.
# The file has 3 sheets: one per technology (2G, 3G, 4G).
# ============================================================
HUAWEI_PM_SERVER = {
    'host':       '10.119.10.104',
    'port':       22,
    'username':   'tooluser',
    'password':   'Zain@1234',
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project/Performance',
}

# Huawei sheet names inside the Excel file → technology label
HUAWEI_SHEET_TECH_MAP = {
    '2G': '2G',
    '3G': '3G',
    '4G': '4G',
}

HUAWEI_PM_COLUMN_MAPS = {
    '2G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
    '3G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
    '4G': {'cell_name': 'Cell Name', 'timestamp': 'Date'},
}


# ============================================================
# SERVER 2 — Metadata
# Root directory contains multiple dated snapshot folders.
# ============================================================
METADATA_SERVER = {
    'host':     '192.168.7.207',
    'port':     22,
    'username': 'ftpuser',
    'password': 'Zain@1234',
    'root_dir': '/home/ftpuser',
}

# Expected filename for each technology inside the snapshot folder.
# Set to None to auto-pick the first file found for that slot.
# ⚠ Update filenames to match what's actually on the server.
METADATA_FILE_MAP = {
    '2G':     None,
    '3G':     None,
    '4G-FDD': None,
    '4G-TDD': None,
    '5G':     None,
}

# Per-technology CSV column maps (CSV header → DB field name).
# Verified against *-2026-02-15.csv snapshot files.
METADATA_CSV_COLUMN_MAPS = {
    '2G': {
        'site_id':          'site_id',
        'site_name':        'site_name',
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        'frequency_band':   'frequency_band',
        'pci':              'bcc',
    },
    '3G': {
        'site_id':          'nodeb_id',
        'site_name':        'nodeb_name',
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        'frequency_band':   'dl_uarfcn',
        'pci':              'psc',
    },
    '4G-FDD': {
        'site_id':          'enb_id_actual',
        'site_name':        'enb_name',
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        'frequency_band':   'band',
        'pci':              'pci',
    },
    '4G-TDD': {
        'site_id':          'enb_id_actual',
        'site_name':        'enb_name',
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        'frequency_band':   'band',
        'pci':              'pci',
    },
    '5G': {
        'site_id':          'gnb_id_actual',
        'site_name':        'gnb_name',
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        'frequency_band':   'bw',
        'pci':              'pci',
    },
}


# ============================================================
# Scheduler settings
# ============================================================
PM_PULL_INTERVAL_HOURS       = 2   # Nokia + Huawei PM pulled every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Metadata pulled once daily

# Local staging directory for downloaded files
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
