"""
SFTP Sync Configuration
Fill in credentials before enabling sync.
"""

# ============================================================================
# SERVER 1 - PM Data (Performance Management)
# Multi-cell hourly KPI data in XLSX format, pulled every 2 hours
# ============================================================================
PM_SERVER = {
    'host': '',           # e.g. '192.168.1.10'
    'port': 22,
    'username': '',       # SFTP username
    'password': '',       # SFTP password
    'remote_dir': '',     # Remote directory path e.g. '/data/pm/'
    'files': {
        '2G': '',         # e.g. 'pm_2g_hourly.xlsx'
        '3G': '',         # e.g. 'pm_3g_hourly.xlsx'
        '4G': '',         # e.g. 'pm_4g_hourly.xlsx'
        '5G': '',         # e.g. 'pm_5g_hourly.xlsx'
    }
}

# ============================================================================
# SERVER 2 - Metadata (Sites Information)
# Site coordinates, azimuth, tilt, name, region — pulled once daily
# ============================================================================
METADATA_SERVER = {
    'host': '',           # e.g. '192.168.1.20'
    'port': 22,
    'username': '',       # SFTP username
    'password': '',       # SFTP password
    'remote_dir': '',     # Remote directory path e.g. '/data/metadata/'
    'files': {
        '2G': '',         # e.g. 'sites_2g.xlsx'
        '3G': '',         # e.g. 'sites_3g.xlsx'
        '4G': '',         # e.g. 'sites_4g.xlsx'
        '5G': '',         # e.g. 'sites_5g.xlsx'
    }
}

# ============================================================================
# Column mappings — update these once you see the actual XLSX headers
# ============================================================================

# PM data column mappings (keys = your DB fields, values = XLSX column names)
PM_COLUMN_MAP = {
    'cell_name':              'Cell Name',
    'timestamp':              'Date',
    'avg_users':              'Average Users',
    'data_volume_gb':         'Data Volume (GB)',
    'rsrp':                   'RSRP',
    'rsrq':                   'RSRQ',
    'sinr':                   'SINR',
    'cqi':                    'CQI',
    'throughput_dl_mbps':     'DL Throughput (Mbps)',
    'throughput_ul_mbps':     'UL Throughput (Mbps)',
    'rrc_success_rate':       'RRC Setup Success Rate',
    'erab_success_rate':      'ERAB Setup Success Rate',
    'call_drop_rate':         'Call Drop Rate',
    'handover_success_rate':  'Handover Success Rate',
    'availability_percent':   'Cell Availability',
}

# Metadata column mappings (keys = your DB fields, values = XLSX column names)
METADATA_COLUMN_MAP = {
    'site_id':          'Site ID',
    'site_name':        'Site Name',
    'latitude':         'Latitude',
    'longitude':        'Longitude',
    'region':           'Region',
    'site_type':        'Site Type',
    'azimuth':          'Azimuth',
    'mechanical_tilt':  'Mechanical Tilt',
}

# ============================================================================
# Scheduler settings
# ============================================================================
PM_PULL_INTERVAL_HOURS = 2      # Pull PM data every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Pull metadata once daily

# Local directory to store downloaded files before processing
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
