"""
SFTP Sync Configuration
=======================
Three data sources:
  Server 1A — Nokia PM    (10.119.219.77)
  Server 1B — Huawei PM   (10.119.10.104)
  Server 2  — Metadata    (192.168.7.207)

Column maps verified against actual sample files (2026-02-15 snapshot):
  - Metadata: CSV files per technology (2G, 3G, 4G FDD, 4G TDD, 5G)
  - Nokia PM: XLSX per technology; 4G headers confirmed from local sample
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

# Nokia KPI column mappings — per-technology dicts  (XLSX header → DB field name)
# Sheet name for each technology:  "<TECH> Performance"  (e.g. "4G Performance")
# Verified against local 2026-02-15 sample files.
NOKIA_PM_COLUMN_MAPS = {
    '2G': {
        'cell_name':             'BTS name',
        'timestamp':             'Period start time',
        'avg_users':             None,
        'data_volume_gb':        None,
        'rsrp':                  None,
        'rsrq':                  None,
        'sinr':                  None,
        'cqi':                   None,
        'throughput_dl_mbps':    None,
        'throughput_ul_mbps':    None,
        'rrc_success_rate':      'Call Setup Success Rate - overall',
        'erab_success_rate':     'Immediate assignment success rate',
        'call_drop_rate':        'Call DR',
        'handover_success_rate': 'HO SR w/o Intracell',
        'availability_percent':  'TCH availability ratio',
    },
    '3G': {
        'cell_name':             'WCEL name',
        'timestamp':             'Period start time',
        'avg_users':             'Average number of simultaneous HSDPA users',
        'data_volume_gb':        None,
        'rsrp':                  'Average CPICH RSCP',
        'rsrq':                  'Average CPICH ECNO',
        'sinr':                  None,
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
        'rsrp':                  None,
        'rsrq':                  None,
        'sinr':                  None,
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
        'data_volume_gb':        None,
        'rsrp':                  None,
        'rsrq':                  None,
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

# Backward-compat alias used by the scheduler (4G map)
NOKIA_PM_COLUMN_MAP = NOKIA_PM_COLUMN_MAPS['4G']


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

# Huawei KPI column mappings — per-technology dicts  (XLSX header → DB field name)
# Source file: Performance.xlsx  (sheets: '4G', '3G', '2G')
# Verified against local 2026-02-15 sample file.
HUAWEI_PM_COLUMN_MAPS = {
    '4G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        'avg_users':             'L.Traffic.User.Avg',
        'data_volume_gb':        'Downlink Traffic Volume (GB)',
        'rsrp':                  None,
        'rsrq':                  None,
        'sinr':                  None,
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
        'sinr':                  None,
        'cqi':                   None,
        'throughput_dl_mbps':    'VS.HSDPA.MeanChThroughput(kbit/s)',
        'throughput_ul_mbps':    'VS.HSUPA.MeanChThroughput(kbit/s)',
        'rrc_success_rate':      'U.RRC Connection Success Rate (Service)(%)',
        'erab_success_rate':     'U.PS RAB Establishment Success Rate (Cell)(%)',
        'call_drop_rate':        'AMR Call Drop Ratio(%)',
        'handover_success_rate': 'Soft Handover Success Ratio (Cell)(%)',
        'availability_percent':  None,   # only unavailability ratio available
    },
    '2G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        'avg_users':             None,
        'data_volume_gb':        'DL Traffic (GB)',
        'rsrp':                  None,
        'rsrq':                  None,
        'sinr':                  None,
        'cqi':                   None,
        'throughput_dl_mbps':    None,
        'throughput_ul_mbps':    None,
        'rrc_success_rate':      'CSSR(%)',
        'erab_success_rate':     'Assignment success Rate TCH(%)',
        'call_drop_rate':        'Drop Call Rate',
        'handover_success_rate': 'Handover Success Rate(%)',
        'availability_percent':  'TCH Availability Rate(%)',
    },
}

# Backward-compat alias used by the scheduler (4G map)
HUAWEI_PM_COLUMN_MAP = HUAWEI_PM_COLUMN_MAPS['4G']


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

# Metadata column mappings  (file header → DB field name)
# Generic/fallback map used when headers already match DB field names.
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

# Per-technology CSV column maps (CSV header → DB field name).
# Verified against *-2026-02-15.csv snapshot files.
# Common fields shared across all technologies:
#   cell_name, vendor, lat→latitude, long→longitude, cluster→region,
#   azimuth, etilt→electrical_tilt, mtilt→mechanical_tilt
METADATA_CSV_COLUMN_MAPS = {
    '2G': {
        # site identification
        'site_id':          'site_id',
        'site_name':        'site_name',
        # cell
        'cell_name':        'cell_name',
        'vendor':           'vendor',
        # location
        'latitude':         'lat',
        'longitude':        'long',
        'region':           'cluster',
        # antenna
        'azimuth':          'azimuth',
        'electrical_tilt':  'etilt',
        'mechanical_tilt':  'mtilt',
        # radio
        'frequency_band':   'frequency_band',
        'pci':              'bcc',       # BCC is the closest 2G analogue
    },
    '3G': {
        # 3G uses nodeb for the site; no site_id column — use nodeb_id
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

# Local staging directory for downloaded files
LOCAL_DOWNLOAD_DIR = 'sync_downloads'
