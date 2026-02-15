"""
SFTP Sync Configuration
Fill in credentials and file paths before enabling sync.
Column mappings will be updated once XLSX headers are confirmed.
"""

# ============================================================
# SERVER 1A — Nokia PM Data
# Multi-cell hourly KPI XLSX, pulled every 2 hours
# Technologies: 2G, 3G, 4G, 5G
# ============================================================
NOKIA_PM_SERVER = {
    'host':       '',        # e.g. '192.168.1.10'
    'port':       22,
    'username':   '',
    'password':   '',
    'remote_dir': '',        # e.g. '/data/nokia/pm/'
    'files': {
        '2G': '',            # e.g. 'nokia_pm_2g.xlsx'
        '3G': '',
        '4G': '',
        '5G': '',
    }
}

# Nokia KPI column mappings (XLSX header → DB field)
# Update these once you open the actual Nokia XLSX files
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
# SERVER 1B — Huawei PM Data
# Multi-cell hourly KPI XLSX, pulled every 2 hours
# Technologies: 2G, 3G, 4G  (no 5G for Huawei)
# ============================================================
HUAWEI_PM_SERVER = {
    'host':       '',        # e.g. '192.168.1.11'
    'port':       22,
    'username':   '',
    'password':   '',
    'remote_dir': '',        # e.g. '/data/huawei/pm/'
    'files': {
        '2G': '',            # e.g. 'huawei_pm_2g.xlsx'
        '3G': '',
        '4G': '',
    }
}

# Huawei KPI column mappings (XLSX header → DB field)
# Update these once you open the actual Huawei XLSX files
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
# SERVER 2 — Metadata (Sites Info)
# Lat/long, azimuth, mechanical tilt, site name, region
# Covers both Nokia and Huawei sites — pulled once daily
# ============================================================
METADATA_SERVER = {
    'host':       '',        # e.g. '192.168.1.20'
    'port':       22,
    'username':   '',
    'password':   '',
    'remote_dir': '',        # e.g. '/data/metadata/'
    'files': {
        '2G': '',
        '3G': '',
        '4G': '',
        '5G': '',
    }
}

# Metadata column mappings
METADATA_COLUMN_MAP = {
    'site_id':         'Site ID',
    'site_name':       'Site Name',
    'latitude':        'Latitude',
    'longitude':       'Longitude',
    'region':          'Region',
    'site_type':       'Site Type',
    'azimuth':         'Azimuth',
    'mechanical_tilt': 'Mechanical Tilt',
}

# ============================================================
# Scheduler settings
# ============================================================
PM_PULL_INTERVAL_HOURS       = 2   # Nokia + Huawei PM pulled every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Metadata pulled once daily

# Local directory to store downloaded files before processing
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
