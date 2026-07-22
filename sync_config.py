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
import sqlite3

# Absolute path to the project root (directory containing this file).
# All other paths are anchored here so the app works regardless of CWD.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv_if_present():
    path = os.path.join(PROJECT_ROOT, '.env')
    if not os.path.isfile(path):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # Prefer values from `.env` over inherited shell/session variables.
    load_dotenv(path, override=True)


_load_dotenv_if_present()

# Persistent data root (databases, sync_downloads, raw). In Docker, mount a volume at NCM_DATA_ROOT.
_DATA_ROOT_OVERRIDE = (os.getenv('NCM_DATA_ROOT') or '').strip()
DATA_ROOT = os.path.abspath(_DATA_ROOT_OVERRIDE) if _DATA_ROOT_OVERRIDE else PROJECT_ROOT

# ── Database files (canonical taxonomy under databases/) ────────────────────
DATABASES_ROOT = os.path.join(DATA_ROOT, 'databases')

# Legacy folder aliases (kept for migration compatibility and old path probes).
CELLS_DB_DIR = os.path.join(DATABASES_ROOT, 'cells')
GROUPS_DB_DIR = os.path.join(DATABASES_ROOT, 'groups')
CELLS_DAILY_DB_DIR = os.path.join(DATABASES_ROOT, 'Cells Daily')
GROUPS_DAILY_DB_DIR = os.path.join(DATABASES_ROOT, 'Groups Daily')
METADATA_DB_DIR = os.path.join(DATABASES_ROOT, 'metadata')
ADMIN_DB_DIR = os.path.join(DATABASES_ROOT, 'admin')

# Canonical domain/vendor/technology/timeframe folders.
DB_PM_NOKIA_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'cells', 'nokia', 'all', 'hourly')
DB_PM_HUAWEI_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'cells', 'huawei', 'all', 'hourly')
DB_PM_NOKIA_DAILY_DIR = os.path.join(DATABASES_ROOT, 'cells', 'nokia', 'all', 'daily')
DB_PM_HUAWEI_DAILY_DIR = os.path.join(DATABASES_ROOT, 'cells', 'huawei', 'all', 'daily')

DB_GROUPS_NOKIA_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'groups', 'nokia', 'all', 'hourly')
DB_GROUPS_HUAWEI_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'groups', 'huawei', 'all', 'hourly')
DB_GROUPS_NOKIA_DAILY_DIR = os.path.join(DATABASES_ROOT, 'groups', 'nokia', 'all', 'daily')
DB_GROUPS_HUAWEI_DAILY_DIR = os.path.join(DATABASES_ROOT, 'groups', 'huawei', 'all', 'daily')

DB_METADATA_SNAPSHOT_DIR = os.path.join(DATABASES_ROOT, 'metadata', 'all', 'all', 'snapshot')
DB_ADMIN_SNAPSHOT_DIR = os.path.join(DATABASES_ROOT, 'admin', 'all', 'all', 'snapshot')
DB_NEIGHBOR_NOKIA_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'neighbors', 'nokia', 'all', 'hourly')
DB_NEIGHBOR_HUAWEI_HOURLY_DIR = os.path.join(DATABASES_ROOT, 'neighbors', 'huawei', 'all', 'hourly')

for _d in (
    CELLS_DB_DIR,
    GROUPS_DB_DIR,
    CELLS_DAILY_DB_DIR,
    GROUPS_DAILY_DB_DIR,
    METADATA_DB_DIR,
    ADMIN_DB_DIR,
    DB_PM_NOKIA_HOURLY_DIR,
    DB_PM_HUAWEI_HOURLY_DIR,
    DB_PM_NOKIA_DAILY_DIR,
    DB_PM_HUAWEI_DAILY_DIR,
    DB_GROUPS_NOKIA_HOURLY_DIR,
    DB_GROUPS_HUAWEI_HOURLY_DIR,
    DB_GROUPS_NOKIA_DAILY_DIR,
    DB_GROUPS_HUAWEI_DAILY_DIR,
    DB_METADATA_SNAPSHOT_DIR,
    DB_ADMIN_SNAPSHOT_DIR,
    DB_NEIGHBOR_NOKIA_HOURLY_DIR,
    DB_NEIGHBOR_HUAWEI_HOURLY_DIR,
):
    os.makedirs(_d, exist_ok=True)

# Canonical DB files.
NOKIA_PM_DB = os.path.join(DB_PM_NOKIA_HOURLY_DIR, 'nokia_pm_cells.db')
HUAWEI_PM_DB = os.path.join(DB_PM_HUAWEI_HOURLY_DIR, 'huawei_pm_cells.db')
NOKIA_PM_DAILY_DB = os.path.join(DB_PM_NOKIA_DAILY_DIR, 'nokia_pm_cells_daily.db')
HUAWEI_PM_DAILY_DB = os.path.join(DB_PM_HUAWEI_DAILY_DIR, 'huawei_pm_cells_daily.db')
METADATA_DB = os.path.join(DB_METADATA_SNAPSHOT_DIR, 'metadata.db')
NCMUSERS_DB = os.path.join(DB_ADMIN_SNAPSHOT_DIR, 'ncm_users.db')
# Admin "Reset Password to Default" and new-user initial password (override in .env).
NCM_DEFAULT_USER_PASSWORD = (os.getenv('NCM_DEFAULT_USER_PASSWORD') or 'Zain@1234').strip()
NEIGHBOR_KPI_DB = os.path.join(DB_NEIGHBOR_NOKIA_HOURLY_DIR, 'neighbor_kpis.db')
HUAWEI_NEIGHBOR_RAW_DB = os.path.join(DB_NEIGHBOR_HUAWEI_HOURLY_DIR, 'huawei_neighbor_raw.db')
NOKIA_GROUPS_DB = os.path.join(DB_GROUPS_NOKIA_HOURLY_DIR, 'nokia_cell_groups.db')
HUAWEI_GROUPS_DB = os.path.join(DB_GROUPS_HUAWEI_HOURLY_DIR, 'huawei_cell_groups.db')
NOKIA_GROUPS_DAILY_DB = os.path.join(DB_GROUPS_NOKIA_DAILY_DIR, 'nokia_cell_groups_daily.db')
HUAWEI_GROUPS_DAILY_DB = os.path.join(DB_GROUPS_HUAWEI_DAILY_DIR, 'huawei_cell_groups_daily.db')

# Backward-compatible directory aliases.
NOKIA_NEIGHBOR_DB_DIR = DB_NEIGHBOR_NOKIA_HOURLY_DIR
HUAWEI_NEIGHBOR_DB_DIR = DB_NEIGHBOR_HUAWEI_HOURLY_DIR
NEIGHBOR_DB_DIR = NOKIA_NEIGHBOR_DB_DIR
KPI_DB_DIR = os.path.join(DATA_ROOT, 'raw', 'KPIs')
os.makedirs(KPI_DB_DIR, exist_ok=True)
KPI_HEADERS_DB = os.path.join(KPI_DB_DIR, 'kpi_headers.db')


def _migrate_legacy_db_names():
    """One-time migration from legacy root DB names to databases/* subfolders."""
    def _sqlite_copy_db(src: str, dst: str) -> bool:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src_conn = sqlite3.connect(src, timeout=10)
            try:
                dst_conn = sqlite3.connect(dst, timeout=10)
                try:
                    src_conn.backup(dst_conn)
                    dst_conn.commit()
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
            return True
        except Exception:
            return False

    def _db_has_nonzero_rows(path: str) -> bool:
        try:
            conn = sqlite3.connect(path, timeout=5)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (table_name,) in tables:
                try:
                    row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                    if row and int(row[0] or 0) > 0:
                        conn.close()
                        return True
                except Exception:
                    continue
            conn.close()
        except Exception:
            return False
        return False

    def _db_total_rows(path: str) -> int:
        try:
            conn = sqlite3.connect(path, timeout=5)
            total = 0
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (table_name,) in tables:
                try:
                    row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                    total += int((row[0] if row else 0) or 0)
                except Exception:
                    continue
            conn.close()
            return total
        except Exception:
            return 0

    legacy_pairs = (
        # PM cells DBs
        (os.path.join(PROJECT_ROOT, 'nokia_pm.db'), NOKIA_PM_DB),
        (os.path.join(PROJECT_ROOT, 'nokia_pm_cells.db'), NOKIA_PM_DB),
        (os.path.join(PROJECT_ROOT, 'huawei_pm.db'), HUAWEI_PM_DB),
        (os.path.join(PROJECT_ROOT, 'huawei_pm_cells.db'), HUAWEI_PM_DB),
        # Metadata / app DBs
        (os.path.join(PROJECT_ROOT, 'metadata.db'), METADATA_DB),
        (os.path.join(PROJECT_ROOT, 'ncm_users.db'), NCMUSERS_DB),
        (os.path.join(PROJECT_ROOT, 'neighbor_kpis.db'), NEIGHBOR_KPI_DB),
        (os.path.join(DATABASES_ROOT, 'admin', 'ncm_users.db'), NCMUSERS_DB),
        (os.path.join(CELLS_DB_DIR, 'metadata.db'), METADATA_DB),
        (os.path.join(CELLS_DB_DIR, 'ncm_users.db'), NCMUSERS_DB),
        (os.path.join(CELLS_DB_DIR, 'neighbor_kpis.db'), NEIGHBOR_KPI_DB),
        (os.path.join(DATABASES_ROOT, 'neighbor_kpis', 'neighbor_kpis.db'), NEIGHBOR_KPI_DB),
        # Group DBs
        (os.path.join(PROJECT_ROOT, 'nokia_cell_groups.db'), NOKIA_GROUPS_DB),
        (os.path.join(PROJECT_ROOT, 'huawei_cell_groups.db'), HUAWEI_GROUPS_DB),
    )
    for old_path, new_path in legacy_pairs:
        if not os.path.isfile(old_path):
            continue
        old_has_data = _db_has_nonzero_rows(old_path)
        if os.path.isfile(new_path):
            # Keep non-empty target DBs; otherwise promote legacy DB if it has data.
            if _db_has_nonzero_rows(new_path):
                old_rows = _db_total_rows(old_path)
                new_rows = _db_total_rows(new_path)
                # If canonical target only has seed rows but legacy has real data, promote legacy content.
                if not (old_rows > new_rows and new_rows <= 20):
                    continue
            if not old_has_data:
                continue
        try:
            os.replace(old_path, new_path)
        except OSError:
            # If file is in use or destination exists, fallback to SQLite backup copy.
            if not old_has_data:
                continue
            try:
                if os.path.isfile(new_path) and not _db_has_nonzero_rows(new_path):
                    os.remove(new_path)
            except OSError:
                pass
            _sqlite_copy_db(old_path, new_path)


_migrate_legacy_db_names()

# ── Database backend ─────────────────────────────────────────────────────────
# SQLite only (local files under ``databases/``). PostgreSQL support was removed.


def use_postgresql() -> bool:
    return False


def postgres_explicitly_enabled() -> bool:
    return False


def probe_postgresql_at_startup(connect_timeout: int = 5) -> None:
    """No-op (legacy hook kept for callers)."""
    return None


def _env_float(key: str, default: float) -> float:
    try:
        raw = os.getenv(key)
        if raw is None or str(raw).strip() == '':
            return default
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        raw = os.getenv(key)
        if raw is None or str(raw).strip() == '':
            return default
        return int(str(raw).strip())
    except ValueError:
        return default


# Nokia + Huawei hourly PM ingest
# PM_SYNC_MODE=full (default) — DELETE/TRUNCATE all rows in each RAT table before ingest.
# PM_SYNC_MODE=incremental — keep existing rows; upsert only from new files (UNIQUE cell_name,timestamp).
#   Best for frequent pulls where exports repeat history and add new timestamps.
_PM_SYNC_RAW = (os.getenv('PM_SYNC_MODE', 'full') or 'full').strip().lower()
PM_SYNC_FULL_CLEAR = _PM_SYNC_RAW not in ('incremental', 'incr', 'merge')

# After each successful PM ingest, delete PM rows with timestamp older than N calendar days.
# Default 14; set PM_RETENTION_DAYS=0 in .env to disable.
PM_RETENTION_DAYS = _env_int('PM_RETENTION_DAYS', 14)

# Rows per SQLite executemany batch inside _insert_df (tune for speed vs. memory).
PM_INSERT_BATCH_SIZE = max(200, min(20000, _env_int('PM_INSERT_BATCH_SIZE', 2500)))

# ── Resource limits (RAM / concurrency) ─────────────────────────────────────
# Lower defaults keep the web UI responsive on shared hosts during pipeline + PM queries.

# Parallel RAT writers inside pm_processor (each contends on one SQLite file).
PM_INGEST_PARALLEL_WORKERS = max(1, min(8, _env_int('PM_INGEST_PARALLEL_WORKERS', 2)))
# Parallel folder loads in load_raw_csv_to_databases.py (was unbounded = len(mappings)).
PIPELINE_MAX_PARALLEL_LOADERS = max(1, min(16, _env_int('PIPELINE_MAX_PARALLEL_LOADERS', 2)))
# CSV rows per pandas chunk during raw → DB load.
PIPELINE_CSV_CHUNK_SIZE = max(5000, min(200_000, _env_int('PIPELINE_CSV_CHUNK_SIZE', 50_000)))

# Concurrent heavy PM table / export / chart queries across Gunicorn threads.
HEAVY_QUERY_MAX_CONCURRENT = max(1, min(8, _env_int('HEAVY_QUERY_MAX_CONCURRENT', 2)))
# Seconds to wait for a query slot (0 = fail immediately with HTTP 503).
HEAVY_QUERY_SLOT_TIMEOUT_SEC = max(0, min(120, _env_int('HEAVY_QUERY_SLOT_TIMEOUT_SEC', 15)))

# PM table export/chart row caps (performance module).
PM_EXPORT_MAX_ROWS = max(1000, min(500_000, _env_int('PM_EXPORT_MAX_ROWS', 200_000)))
PM_CHARTS_MAX_ROWS = max(500, min(50_000, _env_int('PM_CHARTS_MAX_ROWS', 15_000)))

# SQLite read tuning for PM routes (negative cache_size = KiB; 0 = skip custom pragma).
SQLITE_PM_CACHE_SIZE_KB = max(0, min(512_000, _env_int('SQLITE_PM_CACHE_SIZE_KB', 20_000)))
SQLITE_PM_MMAP_SIZE_MB = max(0, min(2048, _env_int('SQLITE_PM_MMAP_SIZE_MB', 64)))

# Adaptive scaling: env ceilings above are reduced automatically when free RAM is low.
def _env_bool(key: str, default: bool) -> bool:
    raw = (os.getenv(key) or '').strip().lower()
    if raw in ('0', 'false', 'no', 'off'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    return default


RESOURCE_ADAPTIVE = _env_bool('RESOURCE_ADAPTIVE', True)
# Never start pipeline / drop to minimum concurrency below this free-RAM reserve (MiB).
RESOURCE_MIN_FREE_MB = max(512, min(64_000, _env_int('RESOURCE_MIN_FREE_MB', 2048)))
# Below this free RAM, concurrency scales toward 1; above RESOURCE_HIGH_MEMORY_MB use full ceiling.
RESOURCE_LOW_MEMORY_MB = max(RESOURCE_MIN_FREE_MB, min(64_000, _env_int('RESOURCE_LOW_MEMORY_MB', 4096)))
RESOURCE_HIGH_MEMORY_MB = max(RESOURCE_LOW_MEMORY_MB + 256, min(128_000, _env_int('RESOURCE_HIGH_MEMORY_MB', 18_432)))

# Hourly pipeline interval (hours) — pull+load orchestrator cadence when scheduler is on.
RAW_PULL_INTERVAL_HOURS = max(1, _env_int('RAW_PULL_INTERVAL_HOURS', 1))
# Daily cycle trigger hour (24h clock) for daily raw+load job.
DAILY_PULL_HOUR = max(0, min(23, _env_int('DAILY_PULL_HOUR', 7)))
# scripts/pipeline/watch_remote_new_files_and_pull.py — poll remote SFTP signatures; same env as the CLI script.
PULL_WATCHER_POLL_INTERVAL_SEC = max(60, _env_int('WATCH_POLL_INTERVAL_SEC', 30 * 60))
# Daily PM/groups DB retention window in days.
DAILY_RETENTION_DAYS = max(1, _env_int('DAILY_RETENTION_DAYS', 120))

# Femto PM SQLite: prune rows older than N days (wide + values tables). Set FEMTO_RETENTION_DAYS=0 to disable.
FEMTO_RETENTION_DAYS = max(0, _env_int('FEMTO_RETENTION_DAYS', 30))


def _env_bool_loader(key: str, default: bool) -> bool:
    """Parse RAW_LOADER_* booleans: 0/false/full/replace vs 1/true/incremental/append."""
    raw = (os.getenv(key) or '').strip().lower()
    if raw in ('0', 'false', 'no', 'full', 'replace'):
        return False
    if raw in ('1', 'true', 'yes', 'incremental', 'append', 'incr'):
        return True
    return default


# scripts/pipeline/load_raw_csv_to_databases.py: for PM + group DBs, append rows not seen before
# (dedupe via stable SHA-256 over sorted columns). Metadata snapshots stay full replace.
RAW_LOADER_INCREMENTAL = _env_bool_loader('RAW_LOADER_INCREMENTAL', True)

# Prefer rows with auto-detected date/time strictly after the table MAX(), then hash-dedupe.
RAW_LOADER_TIME_FILTER = _env_bool_loader('RAW_LOADER_TIME_FILTER', True)

# Incremental PM load: only ingest the newest raw file per RAT (2G/3G/4G/5G).
RAW_LOADER_LATEST_ONLY = _env_bool_loader('RAW_LOADER_LATEST_ONLY', True)

# Daily scope: append new timestamps into *_DAILY tables (retention trims old rows).
# When false, each daily load replaces whole tables (no cross-day history).
RAW_LOADER_DAILY_INCREMENTAL = _env_bool_loader('RAW_LOADER_DAILY_INCREMENTAL', True)

# After a successful PM load, delete all tabular files from raw/ (recommended for OSS hourly/daily drops).
RAW_DELETE_ALL_AFTER_LOAD = _env_bool_loader('RAW_DELETE_ALL_AFTER_LOAD', True)
# Legacy: keep N newest per RAT instead of deleting all (only when RAW_DELETE_ALL_AFTER_LOAD=0).
RAW_PRUNE_AFTER_LOAD = _env_bool_loader('RAW_PRUNE_AFTER_LOAD', True)
RAW_KEEP_FILES_PER_TECH = max(1, _env_int('RAW_KEEP_FILES_PER_TECH', 1))

# pull_nokia_raw.py / pull_huawei_raw.py: run load_raw_csv_to_databases after download.
RAW_PULL_AUTO_LOAD = _env_bool_loader('RAW_PULL_AUTO_LOAD', True)

# Before SFTP pull: delete existing raw PM exports in the target folder.
RAW_PULL_CLEAR_BEFORE = _env_bool_loader('RAW_PULL_CLEAR_BEFORE', True)

# After SFTP pull: keep only the newest RAW_KEEP_FILES_PER_TECH file(s) per RAT.
RAW_PULL_PRUNE_AFTER = _env_bool_loader('RAW_PULL_PRUNE_AFTER', True)

# ── Per-technology PM tables ────────────────────────────────────────────────
# Each PM database stores data in separate tables per technology instead of
# a single cell_kpis table.  Table names: "2G_CELLS_HOURLY", etc.
PM_TECHNOLOGIES = ['2G', '3G', '4G', '5G']

def pm_table_name(technology, scope='hourly'):
    """Map a technology label to its PM database table name.

    '4G', '4G-FDD', '4G-TDD', 'LTE' → '4G_CELLS_HOURLY' (or ``_DAILY`` when
    ``scope`` is daily). Hourly remains the default for callers that omit scope.
    """
    tech = str(technology).upper().strip()
    scope_l = str(scope or 'hourly').strip().lower()
    scope_tag = 'DAILY' if scope_l in ('d', 'day', 'daily') else 'HOURLY'
    if '5G' in tech or 'NR' in tech:
        return f'5G_CELLS_{scope_tag}'
    if '4G' in tech or 'LTE' in tech:
        return f'4G_CELLS_{scope_tag}'
    if '3G' in tech or 'WCDMA' in tech or 'UMTS' in tech:
        return f'3G_CELLS_{scope_tag}'
    if '2G' in tech or 'GSM' in tech:
        return f'2G_CELLS_{scope_tag}'
    return f'{tech}_CELLS_{scope_tag}'

# ============================================================
# SERVER 1A — Nokia PM
# 4 separate technology folders; each contains multiple XLSX
# files — the scheduler downloads the LATEST one per folder.
# ============================================================
NOKIA_PM_SERVER = {
    'host':     (os.getenv('NOKIA_PM_HOST') or '10.119.219.77').strip(),
    'port':     _env_int('NOKIA_PM_PORT', 22),
    'username': (os.getenv('NOKIA_PM_USER') or 'ftpuser').strip(),
    'password': (os.getenv('NOKIA_PM_PASSWORD') or '').strip(),
    'dirs': {
        '2G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/2G',
        '3G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/3G',
        '4G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/4G',
        '5G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project/5G',
    },
    # Some NetAct exports are placed under date/batch subfolders per technology.
    # Enable recursive newest-subfolder search by default.
    'descend_into_newest_subdir': os.getenv('NOKIA_PM_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

NOKIA_PM_DAILY_SERVER = {
    'host':     NOKIA_PM_SERVER['host'],
    'port':     NOKIA_PM_SERVER['port'],
    'username': NOKIA_PM_SERVER['username'],
    'password': NOKIA_PM_SERVER['password'],
    'dirs': {
        '2G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Daily/2G',
        '3G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Daily/3G',
        '4G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Daily/4G',
        '5G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Daily/5G',
    },
    'descend_into_newest_subdir': os.getenv('NOKIA_PM_DAILY_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

# Nokia neighbor relation exports (2G / 3G / 4G only) — same SFTP host as PM.
# Override the whole tree with NOKIA_NEIGHBOR_ROOT, or each RAT with NOKIA_NEIGHBOR_DIR_2G / _3G / _4G.
_NEIGHBOR_ROOT_DEFAULT = (
    '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Neighbor'
)
_NEIGHBOR_ROOT = (os.getenv('NOKIA_NEIGHBOR_ROOT') or _NEIGHBOR_ROOT_DEFAULT).strip() or _NEIGHBOR_ROOT_DEFAULT
NOKIA_NEIGHBOR_SERVER = {
    'host': NOKIA_PM_SERVER['host'],
    'port': NOKIA_PM_SERVER['port'],
    'username': NOKIA_PM_SERVER['username'],
    'password': NOKIA_PM_SERVER['password'],
    'dirs': {
        '2G': os.getenv('NOKIA_NEIGHBOR_DIR_2G', f'{_NEIGHBOR_ROOT}/2G').strip() or f'{_NEIGHBOR_ROOT}/2G',
        '3G': os.getenv('NOKIA_NEIGHBOR_DIR_3G', f'{_NEIGHBOR_ROOT}/3G').strip() or f'{_NEIGHBOR_ROOT}/3G',
        '4G': os.getenv('NOKIA_NEIGHBOR_DIR_4G', f'{_NEIGHBOR_ROOT}/4G').strip() or f'{_NEIGHBOR_ROOT}/4G',
    },
    'descend_into_newest_subdir': os.getenv('NOKIA_NEIGHBOR_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

# SQLite table names for neighbor dumps (see scripts/load_nokia_neighbor_raw_to_db.py).
# 2G/3G use one table each; 4G raw folder is split into intra-eNB vs inter-eNB slim tables.
NOKIA_NEIGHBOR_TECH_TABLES = {
    '2G': 'nokia_neighbor_2g',
    '3G': 'nokia_neighbor_3g',
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
    'host':       (os.getenv('HUAWEI_PM_HOST') or '10.119.10.104').strip(),
    'port':       _env_int('HUAWEI_PM_PORT', 22),
    'username':   (os.getenv('HUAWEI_PM_USER') or 'tooluser').strip(),
    'password':   (os.getenv('HUAWEI_PM_PASSWORD') or '').strip(),
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project/Performance',
    # PRS often drops exports in a date-named subfolder under ``remote_dir``; SFTP then
    # opens the newest subfolder first. Set False if workbooks sit directly in ``remote_dir``.
    'descend_into_newest_subdir': os.getenv('HUAWEI_PM_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

# Huawei neighbor: one .zip on SFTP (contains 2G/3G/4G tabular exports). Pull script routes into raw/huawei/neighbor/<RAT>/.
_HUAWEI_NEIGHBOR_ROOT_DEFAULT = (
    '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/'
    'Performance_Project_Neighbor/Performance Neighbors'
)
_HUAWEI_NEIGHBOR_ROOT = (
    (os.getenv('HUAWEI_NEIGHBOR_ROOT') or _HUAWEI_NEIGHBOR_ROOT_DEFAULT).strip()
    or _HUAWEI_NEIGHBOR_ROOT_DEFAULT
)
HUAWEI_NEIGHBOR_SERVER = {
    'host': HUAWEI_PM_SERVER['host'],
    'port': HUAWEI_PM_SERVER['port'],
    'username': HUAWEI_PM_SERVER['username'],
    'password': HUAWEI_PM_SERVER['password'],
    # Remote folder containing the latest ``*.zip`` bundle (not per-RAT subfolders).
    'zip_remote_dir': (os.getenv('HUAWEI_NEIGHBOR_ZIP_DIR') or '').strip() or _HUAWEI_NEIGHBOR_ROOT,
    'descend_into_newest_subdir': os.getenv('HUAWEI_NEIGHBOR_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

HUAWEI_NEIGHBOR_TECH_TABLES = {
    '2G': 'huawei_neighbor_2g',
    '3G': 'huawei_neighbor_3g',
}

HUAWEI_PM_DAILY_SERVER = {
    'host': HUAWEI_PM_SERVER['host'],
    'port': HUAWEI_PM_SERVER['port'],
    'username': HUAWEI_PM_SERVER['username'],
    'password': HUAWEI_PM_SERVER['password'],
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project_Daily/Performance Daily',
    'descend_into_newest_subdir': os.getenv('HUAWEI_PM_DAILY_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

# ============================================================
# GROUP FILE SOURCES (same SFTP credentials as PM sources)
# ============================================================
NOKIA_GROUPS_SERVER = {
    'host': NOKIA_PM_SERVER['host'],
    'port': NOKIA_PM_SERVER['port'],
    'username': NOKIA_PM_SERVER['username'],
    'password': NOKIA_PM_SERVER['password'],
    'dirs': {
        '2G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance_Project_Groups/2G',
        '3G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance_Project_Groups/3G',
        '4G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance_Project_Groups/4G',
        '5G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance_Project_Groups/5G',
    },
    'descend_into_newest_subdir': os.getenv('NOKIA_GROUPS_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

HUAWEI_GROUPS_SERVER = {
    'host': HUAWEI_PM_SERVER['host'],
    'port': HUAWEI_PM_SERVER['port'],
    'username': HUAWEI_PM_SERVER['username'],
    'password': HUAWEI_PM_SERVER['password'],
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project_Group/Performance Groups',
    'descend_into_newest_subdir': os.getenv('HUAWEI_GROUPS_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

NOKIA_GROUPS_DAILY_SERVER = {
    'host': NOKIA_PM_SERVER['host'],
    'port': NOKIA_PM_SERVER['port'],
    'username': NOKIA_PM_SERVER['username'],
    'password': NOKIA_PM_SERVER['password'],
    'dirs': {
        '2G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Groups Daily/2G',
        '3G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Groups Daily/3G',
        '4G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Groups Daily/4G',
        '5G': '/d/oss/global/var/pm/shared/content3/scheduler/exportCustom/Malek/Performance Project Groups Daily/5G',
    },
    'descend_into_newest_subdir': os.getenv('NOKIA_GROUPS_DAILY_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
}

HUAWEI_GROUPS_DAILY_SERVER = {
    'host': HUAWEI_PM_SERVER['host'],
    'port': HUAWEI_PM_SERVER['port'],
    'username': HUAWEI_PM_SERVER['username'],
    'password': HUAWEI_PM_SERVER['password'],
    'remote_dir': '/export/home/omc/objectstorage/var/prs/result_file/malek.mohammad/Performance_Project_Groups_Daily/Performance Groups Daily',
    'descend_into_newest_subdir': os.getenv('HUAWEI_GROUPS_DAILY_DESCEND_SUBDIR', '1').strip().lower()
    in ('1', 'true', 'yes', 'on'),
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
    'host':     (os.getenv('METADATA_HOST') or '192.168.7.207').strip(),
    'port':     _env_int('METADATA_PORT', 22),
    'username': (os.getenv('METADATA_USER') or 'ftpuser').strip(),
    'password': (os.getenv('METADATA_PASSWORD') or '').strip(),
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
        # Huawei 2G exports 'active_state' (Activated/Deactivated)
        # Nokia  2G exports 'admin_state'  (Unlocked/Locked) — handled as fallback in code
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
LOCAL_DOWNLOAD_DIR = os.path.join(DATA_ROOT, 'sync_downloads')
os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)
