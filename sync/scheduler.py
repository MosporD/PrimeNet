"""
Sync Scheduler
==============
Three background jobs:
  nokia_pm_pull   — every 2 h — downloads latest XLSX from each Nokia tech folder
  huawei_pm_pull  — every 2 h — downloads latest XLSX from Huawei folder, reads 3 sheets
  metadata_pull   — daily     — enters newest snapshot folder, downloads all Excel files from each subfolder
"""

import logging
import sqlite3

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sync.sftp_client import SFTPClient
from sync.pm_processor import run_nokia_pm_sync, process_huawei_pm_file
from sync.metadata_processor import run_metadata_sync
from sync.db_migration import run_migrations

logger = logging.getLogger(__name__)

_scheduler = None


# ---------------------------------------------------------------------------
# Sync log helper
# ---------------------------------------------------------------------------

def _log_sync(sync_type, technology, status, rows=0, message=None):
    try:
        conn = sqlite3.connect('ncm_users.db')
        conn.execute(
            'INSERT INTO sync_log (sync_type, technology, status, rows_affected, message) VALUES (?,?,?,?,?)',
            (sync_type, technology, status, rows, message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f'sync_log write failed: {e}')


# ---------------------------------------------------------------------------
# Nokia PM — one folder per tech, pull latest XLSX from each
# ---------------------------------------------------------------------------

def pull_nokia_pm():
    from sync_config import (
        NOKIA_PM_SERVER, NOKIA_PM_COLUMN_MAPS, LOCAL_DOWNLOAD_DIR
    )
    from sync.metadata_processor import seed_pm_cells_to_metadata
    from sync.pm_processor import NOKIA_PM_DB

    host = NOKIA_PM_SERVER['host']
    if not host:
        logger.warning('Nokia PM server not configured.')
        return

    logger.info('Starting Nokia PM pull...')
    client = SFTPClient(
        host=host,
        port=NOKIA_PM_SERVER['port'],
        username=NOKIA_PM_SERVER['username'],
        password=NOKIA_PM_SERVER['password'],
        local_dir=f'{LOCAL_DOWNLOAD_DIR}/pm_nokia',
    )

    downloaded = {}
    for tech, remote_dir in NOKIA_PM_SERVER['dirs'].items():
        downloaded[tech] = client.download_latest_xlsx(remote_dir, prefix=f'nokia_{tech}_')

    summary = run_nokia_pm_sync(downloaded, NOKIA_PM_COLUMN_MAPS)
    for tech, result in summary.items():
        status = result.get('status', 'error')
        rows   = result.get('inserted', result.get('upserted', 0))
        msg    = result.get('error') or result.get('reason')
        _log_sync('pm_nokia', tech, status, rows, msg)
        logger.info(f'Nokia PM [{tech}]: {result}')

    seed_pm_cells_to_metadata(NOKIA_PM_DB, 'Nokia')
    logger.info('Nokia PM pull complete.')


# ---------------------------------------------------------------------------
# Huawei PM — single folder, single file with 3 sheets (2G/3G/4G)
# ---------------------------------------------------------------------------

def pull_huawei_pm():
    from sync_config import (
        HUAWEI_PM_SERVER, HUAWEI_PM_COLUMN_MAPS, HUAWEI_SHEET_TECH_MAP, LOCAL_DOWNLOAD_DIR
    )
    from sync.metadata_processor import seed_pm_cells_to_metadata
    from sync.pm_processor import HUAWEI_PM_DB

    host = HUAWEI_PM_SERVER['host']
    if not host:
        logger.warning('Huawei PM server not configured.')
        return

    logger.info('Starting Huawei PM pull...')
    client = SFTPClient(
        host=host,
        port=HUAWEI_PM_SERVER['port'],
        username=HUAWEI_PM_SERVER['username'],
        password=HUAWEI_PM_SERVER['password'],
        local_dir=f'{LOCAL_DOWNLOAD_DIR}/pm_huawei',
    )

    local_path = client.download_latest_xlsx(
        HUAWEI_PM_SERVER['remote_dir'],
        prefix='huawei_all_'
    )

    if not local_path:
        logger.error('Huawei PM: no file downloaded.')
        _log_sync('pm_huawei', 'all', 'error', 0, 'Download failed')
        return

    summary = process_huawei_pm_file(local_path, HUAWEI_PM_COLUMN_MAPS, HUAWEI_SHEET_TECH_MAP)
    for tech, result in summary.items():
        status = result.get('status', 'error')
        rows   = result.get('inserted', result.get('upserted', 0))
        msg    = result.get('error') or result.get('reason')
        _log_sync('pm_huawei', tech, status, rows, msg)
        logger.info(f'Huawei PM [{tech}]: {result}')

    seed_pm_cells_to_metadata(HUAWEI_PM_DB, 'Huawei')
    logger.info('Huawei PM pull complete.')


# ---------------------------------------------------------------------------
# Metadata — root dir has dated snapshot folders; enter newest, pull 5 files
# ---------------------------------------------------------------------------

def pull_metadata():
    from sync_config import (
        METADATA_SERVER, METADATA_CSV_COLUMN_MAPS, LOCAL_DOWNLOAD_DIR
    )

    host = METADATA_SERVER['host']
    if not host:
        logger.warning('Metadata server not configured.')
        return

    logger.info('Starting Metadata pull...')
    client = SFTPClient(
        host=host,
        port=METADATA_SERVER['port'],
        username=METADATA_SERVER['username'],
        password=METADATA_SERVER['password'],
        local_dir=f'{LOCAL_DOWNLOAD_DIR}/metadata',
    )

    # Enter the latest dated snapshot folder, then download ALL Excel files
    # from each subfolder inside it (e.g. 2G/, 3G/, 4G-FDD/, 4G-TDD/, 5G/).
    downloaded = client.download_all_xlsx_from_subfolders(
        root_dir=METADATA_SERVER['root_dir'],
        prefix='meta_',
    )

    summary = run_metadata_sync(downloaded, METADATA_CSV_COLUMN_MAPS)
    for tech, result in summary.items():
        status = result.get('status', 'error')
        rows   = result.get('upserted', 0)
        msg    = result.get('error') or result.get('reason')
        _log_sync('metadata', tech, status, rows, msg)
        logger.info(f'Metadata [{tech}]: {result}')

    logger.info('Metadata pull complete.')


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler():
    global _scheduler

    try:
        run_migrations()
    except Exception as e:
        logger.error(f'DB migration failed: {e}')

    from sync_config import PM_PULL_INTERVAL_HOURS, METADATA_PULL_INTERVAL_HOURS

    _scheduler = BackgroundScheduler(daemon=True)

    _scheduler.add_job(
        pull_nokia_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='nokia_pm_pull',
        name='Nokia PM Pull',
        replace_existing=True
    )
    _scheduler.add_job(
        pull_huawei_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='huawei_pm_pull',
        name='Huawei PM Pull',
        replace_existing=True
    )
    _scheduler.add_job(
        pull_metadata,
        trigger=IntervalTrigger(hours=METADATA_PULL_INTERVAL_HOURS),
        id='metadata_pull',
        name='Metadata Pull',
        replace_existing=True
    )

    _scheduler.start()
    logger.info(
        f'Scheduler started — Nokia PM + Huawei PM every {PM_PULL_INTERVAL_HOURS}h, '
        f'Metadata every {METADATA_PULL_INTERVAL_HOURS}h.'
    )


def get_scheduler():
    return _scheduler

# Manual trigger helpers
def trigger_nokia_pm_now():  pull_nokia_pm()
def trigger_huawei_pm_now(): pull_huawei_pm()
def trigger_pm_now():        pull_nokia_pm(); pull_huawei_pm()
def trigger_metadata_now():  pull_metadata()
