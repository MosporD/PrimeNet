"""
SFTP Sync Configuration
=======================
Three data sources:
  Server 1A — Nokia PM    (10.119.219.77)
  Server 1B — Huawei PM   (10.119.10.104)
  Server 2  — Metadata    (192.168.7.207)

Column maps use placeholder header names. Update NOKIA_PM_COLUMN_MAP,
HUAWEI_PM_COLUMN_MAP, and METADATA_COLUMN_MAP once you upload sample
Excel files so we can read the real headers.
"""

# ============================================================
# SERVER 1A — Nokia PM
# 4 separate technology folders; each contains multiple XLSX
# files — the scheduler downloads the LATEST one per folder.
# Technologies: 2G, 3G, 4G, 5G
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

# Nokia KPI column mappings  (XLSX header → DB field name)
# ⚠ Update these values with the real column headers from your Nokia Excel files.
NOKIA_PM_COLUMN_MAP = {
    'cell_name':             'Cell Name',
    'timestamp':             'Date',
    'avg_users':             'Average Users',
    'data_volume_gb':        'Data Volume (GB)',
    'rsrp':                  'RSRP',
    'rsrq':                  'RSRQ',
    'sinr':                  'SINR',
    'cqi':                   'CQI',
    'throughput_dl_mbps':    'DL Throughput (Mbps)',
    'throughput_ul_mbps':    'UL Throughput (Mbps)',
    'rrc_success_rate':      'RRC Setup Success Rate',
    'erab_success_rate':     'ERAB Setup Success Rate',
    'call_drop_rate':        'Call Drop Rate',
    'handover_success_rate': 'Handover Success Rate',
    'availability_percent':  'Cell Availability',
}


# ============================================================
# SERVER 1B — Huawei PM
# Single folder containing one XLSX file; the scheduler
# downloads the LATEST file in that folder.
# The file has 3 sheets: one per technology (2G, 3G, 4G).
# Technologies: 2G, 3G, 4G  (no 5G for Huawei)
# ============================================================
HUAWEI_PM_SERVER = {
    'host':       '10.119.10.104',
    'port':       22,
    'username':   'tooluser',
    'password':   'Zain@1234',
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project/Performance',
}

# Huawei sheet names inside the Excel file → technology label
# ⚠ Update the right-hand values if the sheet names differ from these defaults.
HUAWEI_SHEET_TECH_MAP = {
    '2G': '2G',
    '3G': '3G',
    '4G': '4G',
}

# Huawei KPI column mappings  (XLSX header → DB field name)
# ⚠ Update these with real column headers from your Huawei Excel file.
HUAWEI_PM_COLUMN_MAP = {
    'cell_name':             'Cell Name',
    'timestamp':             'Date',
    'avg_users':             'Average Users',
    'data_volume_gb':        'Data Volume (GB)',
    'rsrp':                  'RSRP',
    'rsrq':                  'RSRQ',
    'sinr':                  'SINR',
    'cqi':                   'CQI',
    'throughput_dl_mbps':    'DL Throughput (Mbps)',
    'throughput_ul_mbps':    'UL Throughput (Mbps)',
    'rrc_success_rate':      'RRC Setup Success Rate',
    'erab_success_rate':     'ERAB Setup Success Rate',
    'call_drop_rate':        'Call Drop Rate',
    'handover_success_rate': 'Handover Success Rate',
    'availability_percent':  'Cell Availability',
}


# ============================================================
# SERVER 2 — Metadata
# Root directory contains multiple dated snapshot folders.
# The scheduler enters the NEWEST folder and downloads one
# file per technology (5 files: 2G, 3G, 4G-FDD, 4G-TDD, 5G).
# ============================================================
METADATA_SERVER = {
    'host':     '192.168.7.207',
    'port':     22,
    'username': 'ftpuser',
    'password': 'Zain@1234',
    # ⚠ Set to the root directory that contains the dated snapshot folders.
    # e.g. '/home/ftpuser/metadata' or '/data/network/metadata'
    'root_dir': '/home/ftpuser',
}

# Expected filename for each technology inside the snapshot folder.
# Set to None to auto-pick the first XLSX found for that slot.
# ⚠ Update filenames to match what's actually on the server.
METADATA_FILE_MAP = {
    '2G':     None,       # e.g. '2G.xlsx'
    '3G':     None,       # e.g. '3G.xlsx'
    '4G-FDD': None,       # e.g. '4G-FDD.xlsx'
    '4G-TDD': None,       # e.g. '4G-TDD.xlsx'
    '5G':     None,       # e.g. '5G.xlsx'
}

# Metadata column mappings  (XLSX header → DB field name)
# ⚠ Update with real column headers from your metadata Excel files.
METADATA_COLUMN_MAP = {
    'site_id':          'Site ID',
    'site_name':        'Site Name',
    'cell_name':        'Cell Name',
    'vendor':           'Vendor',
    'latitude':         'Latitude',
    'longitude':        'Longitude',
    'region':           'Region',
    'site_type':        'Site Type',
    'frequency_band':   'Frequency Band',
    'azimuth':          'Azimuth',
    'mechanical_tilt':  'Mechanical Tilt',
    'electrical_tilt':  'Electrical Tilt',
    'pci':              'PCI',
}


# ============================================================
# Scheduler settings
# ============================================================
PM_PULL_INTERVAL_HOURS       = 2   # Nokia + Huawei PM pulled every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Metadata pulled once daily

# Local staging directory for downloaded files
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
