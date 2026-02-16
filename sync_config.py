"""
SFTP Sync Configuration
=======================
Three data sources:
  Server 1A — Nokia PM    (10.119.219.77)
  Server 1B — Huawei PM   (10.119.10.104)
  Server 2  — Metadata    (192.168.7.207)

Column detection is fully automatic — no mapping configuration needed.
Files are stored with their original header names.
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


# ============================================================
# SERVER 1B — Huawei PM
# Single folder containing one XLSX file with multiple sheets.
# ============================================================
HUAWEI_PM_SERVER = {
    'host':       '10.119.10.104',
    'port':       22,
    'username':   'tooluser',
    'password':   'Zain@1234',
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project/Performance',
}


# ============================================================
# SERVER 2 — Metadata
# Root directory contains multiple dated snapshot folders.
# Each folder contains Atoll-exported CSVs:
#   Site 3G - YYYY-MM-DD.csv, Site L18 - YYYY-MM-DD.csv, …
#   Transmitter 2G - YYYY-MM-DD.csv, …
# ============================================================
METADATA_SERVER = {
    'host':     '192.168.7.207',
    'port':     22,
    'username': 'ftpuser',
    'password': 'Zain@1234',
    'root_dir': '/',   # dated snapshot folders sit at the SFTP root
}


# ============================================================
# Scheduler settings
# ============================================================
PM_PULL_INTERVAL_HOURS       = 2   # Nokia + Huawei PM pulled every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Metadata pulled once daily

# Local staging directory for downloaded files
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
