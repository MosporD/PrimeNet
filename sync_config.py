"""
SFTP Sync Configuration
=======================
Three data sources:
  Server 1A — Nokia PM    (10.119.219.77)
  Server 1B — Huawei PM   (10.119.10.104)
  Server 2  — Metadata    (192.168.7.207)

PM column detection is fully automatic (no mapping needed at runtime).
Column maps below are kept as reference / used by import_local_files.py.
"""

import os

# Absolute path to the project root (directory containing this file).
# All other paths are anchored here so the app works regardless of CWD.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Database files (all in project root) ────────────────────────────────────
NOKIA_PM_DB  = os.path.join(PROJECT_ROOT, 'nokia_pm.db')
HUAWEI_PM_DB = os.path.join(PROJECT_ROOT, 'huawei_pm.db')
METADATA_DB  = os.path.join(PROJECT_ROOT, 'metadata.db')
NCMUSERS_DB  = os.path.join(PROJECT_ROOT, 'ncm_users.db')

# ── Per-technology PM tables ────────────────────────────────────────────────
# Each PM database stores data in separate tables per technology instead of
# a single cell_kpis table.  Table names: "2G_Hourly", "3G_Hourly", etc.
PM_TECHNOLOGIES = ['2G', '3G', '4G', '5G']

def pm_table_name(technology):
    """Map a technology label to its PM database table name.
    '4G', '4G-FDD', '4G-TDD', 'LTE' → '4G_Hourly', etc."""
    tech = str(technology).upper().strip()
    if '5G' in tech or 'NR' in tech:
        return '5G_Hourly'
    if '4G' in tech or 'LTE' in tech:
        return '4G_Hourly'
    if '3G' in tech or 'WCDMA' in tech or 'UMTS' in tech:
        return '3G_Hourly'
    if '2G' in tech or 'GSM' in tech:
        return '2G_Hourly'
    return f'{tech}_Hourly'

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

# Nokia KPI column mappings — per-technology dicts  (XLSX header → DB field name)
# Used by import_local_files.py; runtime scheduler uses auto-detection instead.
# ⚠ Update these if the actual file headers differ.
NOKIA_PM_COLUMN_MAPS = {
    '2G': {
        'cell_name':             'BTS name',
        'timestamp':             'Period start time',
        'rrc_success_rate':      'Call Setup Success Rate - overall',
        'call_drop_rate':        'Call DR',
        'handover_success_rate': 'HO SR w/o Intracell',
        'availability_percent':  'TCH availability ratio',
    },
    '3G': {
        'cell_name':             'WCEL name',
        'timestamp':             'Period start time',
        'avg_users':             'Average number of simultaneous HSDPA users',
        'rsrp':                  'Average CPICH RSCP',
        'rsrq':                  'Average CPICH ECNO',
        'cqi':                   'Avg reported CQI',
        'throughput_dl_mbps':    'HSDPA Cell thp',
        'throughput_ul_mbps':    'Active  HSUPA cell thp',
        'rrc_success_rate':      'RRC Success Rate (Total)(%)',
        'erab_success_rate':     'U.PS RAB Establishment Success Rate (Cell)(%)',
        'call_drop_rate':        'AMR Call Drop Ratio(%)',
        'handover_success_rate': 'Soft HO Success rate, RT',
        'availability_percent':  'Cell Availability',
    },
    '4G': {
        'cell_name':             'LNCEL name',
        'timestamp':             'Period start time',
        'avg_users':             'Avg act UEs DL',
        'data_volume_gb':        'PDCP SDU Volume, DL (GB)',
        'cqi':                   'Average CQI',
        'throughput_dl_mbps':    'Avg PDCP cell thp DL (Mbps)',
        'throughput_ul_mbps':    'Avg PDCP cell thp UL (Mbps)',
        'rrc_success_rate':      'Total E-UTRAN RRC conn stp SR',
        'erab_success_rate':     'E-UTRAN E-RAB stp SR',
        'call_drop_rate':        'E-UTRAN E-RAB Drop Ratio, User Perspective',
        'handover_success_rate': 'E-UTRAN Intra-Freq HO SR',
        'availability_percent':  'Cell Avail',
    },
    '5G': {
        'cell_name':             'NRCEL name',
        'timestamp':             'Period start time',
        'avg_users':             'Avg nr act UEs data buff DRBs DL',
        'sinr':                  'Avg UE rel SINR PUSCH rank1',
        'cqi':                   'Avg wb CQI 256QAM',
        'throughput_dl_mbps':    'Act cell MAC thp PDSCH',
        'throughput_ul_mbps':    'Act cell MAC thp PUSCH',
        'rrc_success_rate':      'Act RACH stp SR',
        'erab_success_rate':     'RB estab SR',
        'call_drop_rate':        'UE rel R abnorm rel',
        'handover_success_rate': 'IntergNB HO SR NSA',
        'availability_percent':  'Cell avail R',
    },
}

# Backward-compat alias
NOKIA_PM_COLUMN_MAP = NOKIA_PM_COLUMN_MAPS['4G']


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

# Huawei sheet names inside the Excel file → technology label
HUAWEI_SHEET_TECH_MAP = {
    '2G': '2G',
    '3G': '3G',
    '4G': '4G',
}

# Huawei KPI column mappings — per-technology dicts  (XLSX header → DB field name)
# Used by import_local_files.py; runtime scheduler uses auto-detection instead.
HUAWEI_PM_COLUMN_MAPS = {
    '4G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        'avg_users':             'L.Traffic.User.Avg',
        'data_volume_gb':        'Downlink Traffic Volume (GB)',
        'cqi':                   'Average CQI',
        'throughput_dl_mbps':    'User DL PDCP Average Throughput (Mbps)',
        'throughput_ul_mbps':    'User UL PDCP Average Throughput (Mbps)',
        'rrc_success_rate':      'RRC Setup Success Rate(%)',
        'erab_success_rate':     'E-RAB Setup Success Rate (ALL)(%)',
        'call_drop_rate':        'Call Drop Rate (All)(%)',
        'handover_success_rate': 'Intra-Freq HO Success Rate(%)',
        'availability_percent':  'Radio Network Availability Rate(%)',
    },
    '3G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        'avg_users':             'VS.HSDPA.UE.Mean.Cell',
        'data_volume_gb':        'HSDPA Traffic (GB)',
        'rsrp':                  'VS.MeanTCP(dBm)',
        'rsrq':                  'VS.MeanRTWP(dBm)',
        'throughput_dl_mbps':    'VS.HSDPA.MeanChThroughput(kbit/s)',
        'throughput_ul_mbps':    'VS.HSUPA.MeanChThroughput(kbit/s)',
        'rrc_success_rate':      'U.RRC Connection Success Rate (Service)(%)',
        'erab_success_rate':     'U.PS RAB Establishment Success Rate (Cell)(%)',
        'call_drop_rate':        'AMR Call Drop Ratio(%)',
        'handover_success_rate': 'Soft Handover Success Ratio (Cell)(%)',
    },
    '2G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        'data_volume_gb':        'DL Traffic (GB)',
        'rrc_success_rate':      'CSSR(%)',
        'erab_success_rate':     'Assignment success Rate TCH(%)',
        'call_drop_rate':        'Drop Call Rate',
        'handover_success_rate': 'Handover Success Rate(%)',
        'availability_percent':  'TCH Availability Rate(%)',
    },
}

# Backward-compat alias
HUAWEI_PM_COLUMN_MAP = HUAWEI_PM_COLUMN_MAPS['4G']


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
        'pci':              'bcc',       # BCC is the closest 2G analogue
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
        'pci':              'psc',       # Primary Scrambling Code
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

# Local staging directory for downloaded files (absolute path)
LOCAL_DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, 'sync_downloads')
