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
# Verified against actual live file headers (2026-02-18 snapshot).
NOKIA_PM_COLUMN_MAPS = {
    # ── Nokia 2G ─────────────────────────────────────────────────────────────
    # File: nokia_2G_<date>.xlsx  Sheet: [2G Performance] (or similar)
    '2G': {
        'cell_name':             'BTS name',
        'timestamp':             'Period start time',
        'rrc_success_rate':      'Call Setup Success Rate - overall',
        'call_drop_rate':        'Call DR',
        'handover_success_rate': 'HO SR w/o Intracell',
        'availability_percent':  'TCH availability ratio',
    },
    # ── Nokia 3G ─────────────────────────────────────────────────────────────
    # File: nokia_3G_<date>.xlsx  Sheet: [3G Performance] (or similar)
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
    # ── Nokia 4G ─────────────────────────────────────────────────────────────
    # File: nokia_4G_<date>.xlsx  Sheet: [4G Performance] (or similar)
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
    # ── Nokia 5G ─────────────────────────────────────────────────────────────
    # Verified against: nokia_5G_20260218_1005_5G-42731-2026_02_18-10_00_11__558.xlsx
    # Sheet: [5G Performance]
    '5G': {
        'cell_name':             'NRCEL name',
        'timestamp':             'Period start time',
        # Traffic / users
        'avg_users':             'Avg nr act UEs data buff DRBs DL',
        'avg_users_ul':          'Avg nr act UEs data buff DRBs UL',
        'max_users':             'Max nr NSA user',
        'nsa_avg_users':         'NSA Avg nr user',
        # Throughput
        'throughput_dl_mbps':    'Act cell MAC thp PDSCH',
        'throughput_ul_mbps':    'Act cell MAC thp PUSCH',
        'user_thp_dl':           'Sched user thp DL',
        'dl_pdcp_thp':           'DL PDCP SDU NR leg throughput per DRB',
        # Radio quality
        'sinr':                  'Avg UE rel SINR PUSCH rank1',
        'sinr_pucch':            'Avg UE rel SINR PUCCH',
        'rssi_pusch':            'Avg UE rel RSSI PUSCH',
        'rssi_pucch':            'Avg UE rel RSSI PUCCH',
        'cqi':                   'Avg wb CQI 256QAM',
        'cqi_64qam':             'Avg wb CQI 64QAM',
        'avg_dl_rank':           'Avg DL rank',
        'rank4_share':           'Rank4 share DL',
        # Modulation
        'dl_qpsk_ratio':         'R init tx QPSK DL',
        'dl_16qam_ratio':        'R init tx 16QAM DL',
        'dl_64qam_ratio':        'R init tx 64QAM DL',
        'dl_256qam_ratio':       'R init tx 256QAM DL',
        'ul_qpsk_ratio':         'R init tx QPSK UL',
        'ul_16qam_ratio':        'R init tx 16QAM UL',
        'ul_64qam_ratio':        'R init tx 64QAM UL',
        'ul_256qam_ratio':       'R init tx 256QAM UL',
        # BLER
        'dl_init_bler':          'Init BLER DL PDSCH tx',
        'ul_init_bler':          'UL init BLER PUSCH 64QAM tab',
        'ul_resid_bler':         'UL resid BLER PUSCH',
        # PRB utilization
        'prb_util_dl':           'PRB util PDSCH',
        'prb_util_ul':           'PRB util PUSCH',
        # Spectral efficiency
        'spectr_effic_dl':       'Spectr effic DL',
        'spectr_effic_ul':       'Spectr effic UL',
        # Data volume (MAC layer)
        'data_vol_dl_mac':       'MAC SDU data vol trans DL DTCH',
        'data_vol_ul_mac':       'MAC SDU data vol rcvd UL DTCH',
        # Success rates
        'rrc_success_rate':      'Act RACH stp SR',
        'erab_success_rate':     'RB estab SR',
        'sgnb_add_prep_sr':      'SgNB add prep SR',
        'sgnb_reconfig_sr':      'SgNB reconfig SR',
        'cont_rach_sr':          'Cont based RACH stp SR',
        'intrafreq_psc_exec_sr': 'Inafreq inaDU PSC change exec SR',
        # Handover
        'handover_success_rate': 'IntergNB HO SR NSA',
        'ho_att_nsa':            'IntergNB HO att NSA',
        # Drops / releases
        'call_drop_rate':        'UE rel R abnorm rel',
        'sgnb_abnorm_rel':       'SgNB abnorm rel per con h',
        'nsa_rlf_drops':         'NSA Nr UE rel RLF',
        # Availability
        'availability_percent':  'Cell avail R',
        'avail_excl_blu':        'Cell avail exclud BLU',
        # UE distances
        'avg_ue_dist_rach':      'Avg UE dist RACH stp',
        'avg_ue_dist_rrc':       'Avg UE dist RRC con',
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
# Verified against: huawei_all_20260218_1006_Performance.xlsx (sheets: 2G, 3G, 4G)
HUAWEI_PM_COLUMN_MAPS = {
    # ── Huawei 2G ────────────────────────────────────────────────────────────
    # Sheet [2G] — key identifier columns: GBSC, Cell CI, Cell Name
    '2G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        # Traffic
        'data_volume_gb':        'DL Traffic (GB)',
        'tch_traffic_erl':       '*K3014: Traffic Volume on TCH(Erl)',
        'tch_total_erl':         'TCH Erlang Total(Erl)',
        'sdcch_traffic_erl':     'K3004:Traffic Volume on SDCCH(Erl)',
        'tchh_traffic':          'TCHH Traffic(Erl)',
        # Voice quality
        'efr_vqi_dl':            'T3279:EFR Average Downlink VQI',
        'amr_fr_vqi_dl':         'T3282:AMR FR Average Downlink VQI',
        'amr_hr_vqi_dl':         'T3285:AMR HR Average Downlink VQI',
        # Success rates / KPIs
        'rrc_success_rate':      'CSSR(%)',
        'imm_assign_sr':         'Immediate Assignment Success Rate(%)',
        'imm_assign_sr_no_lu':   'Immediate Assignment Success Rate (No LU)(%)',
        'erab_success_rate':     'Assignment success Rate TCH(%)',
        'call_drop_rate':        'Drop Call Rate',
        'handover_success_rate': 'Handover Success Rate(%)',
        'ho_incoming_sr':        'TH323:Success Rate of Incoming Internal Inter-Cell Handovers(%)',
        'availability_percent':  'TCH Availability Rate(%)',
        # Congestion / blocking
        'tch_blocking_rate':     'TCH Blocking Rate(%)',
        'tch_congestion_rate':   'TCH Congestion Rate(%)',
        'sdcch_blocking_rate':   'SDCCH Blocking Rate(%)',
        'sdcch_congestion_rate': 'SDCCH Congestion Rate(%)',
        # SDCCH / Drop rates
        'sdcch_drop_rate':       'SDCCH Drop Rate(%)',
        'sdcch_drop_rate_hw':    'SDCCH Drop Rate -HW(%)',
        # TBF (GPRS/EDGE)
        'dl_tbf_sr':             'DL TBF Success Rate(%)',
        'ul_tbf_sr':             'UL TBF Success Rate(%)',
        'dl_tbf_drop_rate':      'Downlink TBF Drop Rate',
        'ul_tbf_drop_rate':      'Uplink TBF Drop Rate',
        # Timing advance
        'mean_ta':               'Mean Ta(ta)',
    },
    # ── Huawei 3G ────────────────────────────────────────────────────────────
    # Sheet [3G] — key identifier columns: RNC, Cell ID, Cell Name, NodeB Name
    '3G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        # Users / traffic
        'avg_users':             'VS.HSDPA.UE.Mean.Cell',
        'avg_users_ul':          'VS.HSUPA.UE.Mean.Cell',
        'data_volume_gb':        'HSDPA Traffic (GB)',
        'data_volume_ul_gb':     'HSUPA Traffic (GB)',
        'amr_traffic_erl':       'AMR Traffic(Erl)',
        'cs_traffic_erl':        'CS Traffic (Erl)',
        # Radio quality
        'rsrp':                  'VS.MeanTCP(dBm)',
        'rsrq':                  'VS.MeanRTWP(dBm)',
        'avg_ue_distance':       'UCELL.UE.TP.MEAN.DISTANCE(m)',
        # Throughput
        'throughput_dl_mbps':    'VS.HSDPA.MeanChThroughput(kbit/s)',
        'throughput_ul_mbps':    'VS.HSUPA.MeanChThroughput(kbit/s)',
        # Success rates
        'rrc_success_rate':      'U.RRC Connection Success Rate (Service)(%)',
        'rrc_sr_other':          'U.RRC Connection Success Rate (Other)(%)',
        'erab_success_rate':     'U.PS RAB Establishment Success Rate (Cell)(%)',
        'erab_cs_sr':            'U.AMR RAB Establishment Success Rate (Cell)(%)',
        'hsdpa_rab_sr':          'HSDPA RAB Setup Success Rate(%)',
        # Call drops
        'call_drop_rate':        'AMR Call Drop Ratio(%)',
        'ps_cdr_dch':            'U.PS CDR (DCH)(%)',
        'ps_cdr_pch':            'U.PS CDR (PCH)(%)',
        'ps_cdr_setup':          'U.PS CDR (Setup)(%)',
        'hsdpa_drop_rate':       'HSDPA Call Drop Ratio (Cell)(%)',
        # Handover
        'handover_success_rate': 'Soft Handover Success Ratio (Cell)(%)',
        'softer_ho_sr':          'Softer Handover Success Rate (Cell)(%)',
        'sho_overhead':          'Soft Handover Overhead (Cell)(%)',
        'ps_irat_sr':            'PS IRAT Success Rate(%)',
        # Voice quality
        'vqi_amr_dl':            'MHR. EVQI.AMRNB.DL',
        'vqi_amr_ul':            'MHR. EVQI.AMRNB.UL',
        # Congestion
        'ps_congestion_rate':    'VS.PS.Congestion.Rate(%)',
        'rrc_congestion_rate':   'U.RRC Congestion Rate(%)',
        'cs_congestion_rate':    'VS.CS.Congestion.Rate(%)',
        # Availability
        'unavailability_ratio':  'Radio Network Unavailability Ratio',
    },
    # ── Huawei 4G ────────────────────────────────────────────────────────────
    # Sheet [4G] — key identifier columns: eNodeB Name, Cell Name
    '4G': {
        'cell_name':             'Cell Name',
        'timestamp':             'Date',
        # Users / traffic
        'avg_users':             'L.Traffic.User.Avg',
        'avg_active_users_dl':   'L.Traffic.ActiveUser.DL.Avg',
        'avg_voip_users':        'L.Traffic.User.VoIP.Avg',
        'data_volume_gb':        'Downlink Traffic Volume (GB)',
        'data_volume_ul_gb':     'Uplink Traffic Volume (GB)',
        # Throughput
        'throughput_dl_mbps':    'User DL PDCP Average Throughput (Mbps)',
        'throughput_ul_mbps':    'User UL PDCP Average Throughput (Mbps)',
        'cell_thp_dl':           'Cell DL Average Throughput(Mbps)',
        'cell_thp_ul':           'Cell UL Average Throughput(Mbps)',
        'ca_user_thp_dl':        'CA DL User Throughput',
        # Radio quality
        'cqi':                   'Average CQI',
        'pdsch_mcs':             'Average PDSCH MCS',
        'pusch_mcs':             'Average PUSCH MCS',
        'ul_interference':       'L.UL.Interference.Avg(dBm)',
        'rank2_ratio':           'Rank 2 Ratio(%)',
        # PRB utilization
        'prb_util_dl':           'DL PRB Usage Rate(%)',
        'prb_util_ul':           'UL PRB Usage Rate(%)',
        # BLER
        'dl_ibler':              'DL IBLER(%)',
        'ul_ibler':              'UL IBLER(%)',
        'dl_rbler':              'DL RBLER (%)(%))',
        'ul_rbler':              'UL RBLER (%)(%))',
        # Modulation
        'dl_qpsk_ratio':         'DL QPSK Ratio (%)(%))',
        'dl_16qam_ratio':        'DL 16QAM Ratio (%)(%))',
        'dl_64qam_ratio':        'DL 64QAM Ratio (%)(%))',
        # Success rates
        'rrc_success_rate':      'RRC Setup Success Rate(%)',
        'erab_success_rate':     'E-RAB Setup Success Rate (ALL)(%)',
        'erab_sr_qci1':          'ERAB Setup Success Rate QCI1(%)',
        'erab_sr_qci5':          'ERAB Setup Success Rate QCI5(%)',
        's1sig_sr':              'S1 Sig Setup Success Rate(%)',
        'rach_sr':               'Random Access Success Rate(%)',
        'csfb_sr':               'CSFB Success Rate(%)',
        'srvcc_sr':              'IRAT SRVCC Execution Success Rate(%)',
        # Drop rates
        'call_drop_rate':        'Call Drop Rate (All)(%)',
        'drop_rate_excl_e2w':    'Call Drop Rate Excluding E2W (AQ)',
        'voip_drop_rate':        'Call Drop Rate (VoIP)(%)',
        # Handover
        'handover_success_rate': 'Intra-Freq HO Success Rate(%)',
        'ho_in_sr':              'Handover In Success Rate(%)',
        'voip_intrafreq_ho_sr':  'Intra-Freq Handover Out SR (VoIP) - Execution(%)',
        # VoIP / Voice quality
        'voip_dl_pkt_loss':      'DL Packet Loss Rate(VoIP)(%)',
        'voip_ul_pkt_loss':      'UL Packet Loss Rate(VoIP)(%)',
        'vqi_dl_excellent':      'L.Voice.VQI.DL.Excellent.Times',
        'vqi_dl_good':           'L.Voice.VQI.DL.Good.Times',
        'vqi_dl_poor':           'L.Voice.VQI.DL.Poor.Times',
        'vqi_dl_bad':            'L.Voice.VQI.DL.Bad.Times',
        # Carrier aggregation
        'ca_avg_ue':             'L.CA.UE.Avg',
        'ca_3cc_ratio':          'HJ_ % Of 3CC Users(%)',
        # Availability
        'availability_percent':  'Radio Network Availability Rate(%)',
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
        'pci':              'bcc',          # BCC is the closest 2G analogue
        'status':           'active_state',
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
        'pci':              'psc',          # Primary Scrambling Code
        'status':           'active_state',
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
        'status':           'active_state',
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
        'status':           'active_state',
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
        'status':           'active_state',
    },
}


# ============================================================
# Scheduler settings
# ============================================================
PM_PULL_INTERVAL_HOURS       = 2   # Nokia + Huawei PM pulled every 2 hours
METADATA_PULL_INTERVAL_HOURS = 24  # Metadata pulled once daily

# Local staging directory for downloaded files (absolute path)
LOCAL_DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, 'sync_downloads')
