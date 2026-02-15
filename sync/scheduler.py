"""
Sync Scheduler
Pulls Nokia PM + Huawei PM every 2 hours, metadata daily.
"""

import logging
import sqlite3
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sync.sftp_client import SFTPClient
from sync.pm_processor import run_pm_sync
from sync.metadata_processor import run_metadata_sync
from sync.db_migration import run_migrations

logger = logging.getLogger(__name__)

_scheduler = None


def _log_sync(sync_type, technology, status, rows_affected=0, message=None):
    try:
        conn = sqlite3.connect('ncm_users.db')
        conn.execute(
            'INSERT INTO sync_log (sync_type, technology, status, rows_affected, message) VALUES (?,?,?,?,?)',
            (sync_type, technology, status, rows_affected, message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f'Failed to write sync log: {e}')


def _pull_pm_server(server_cfg, column_map, vendor_label):
    """Download and process PM files from one vendor server."""
    if not server_cfg['host']:
        logger.warning(f'{vendor_label} PM server not configured, skipping.')
        return

    logger.info(f'Starting {vendor_label} PM pull...')
    from sync_config import LOCAL_DOWNLOAD_DIR
    client = SFTPClient(
        host=server_cfg['host'],
        port=server_cfg['port'],
        username=server_cfg['username'],
        password=server_cfg['password'],
        remote_dir=server_cfg['remote_dir'],
        local_dir=f"{LOCAL_DOWNLOAD_DIR}/pm_{vendor_label.lower()}"
    )

    downloaded = client.download_all(server_cfg['files'])
    summary    = run_pm_sync(downloaded, column_map)

    for tech, result in summary.items():
        status = result.get('status', 'error')
        rows   = result.get('inserted', result.get('upserted', 0))
        msg    = result.get('error') or result.get('reason')
        _log_sync(f'pm_{vendor_label.lower()}', tech, status, rows, msg)
        logger.info(f'{vendor_label} PM [{tech}]: {result}')

    logger.info(f'{vendor_label} PM pull complete.')


def pull_nokia_pm():
    """Job: pull Nokia PM data."""
    from sync_config import NOKIA_PM_SERVER, NOKIA_PM_COLUMN_MAP
    _pull_pm_server(NOKIA_PM_SERVER, NOKIA_PM_COLUMN_MAP, 'Nokia')


def pull_huawei_pm():
    """Job: pull Huawei PM data."""
    from sync_config import HUAWEI_PM_SERVER, HUAWEI_PM_COLUMN_MAP
    _pull_pm_server(HUAWEI_PM_SERVER, HUAWEI_PM_COLUMN_MAP, 'Huawei')


def pull_metadata():
    """Job: pull metadata from server 2."""
    from sync_config import METADATA_SERVER, METADATA_COLUMN_MAP, LOCAL_DOWNLOAD_DIR

    if not METADATA_SERVER['host']:
        logger.warning('Metadata server not configured, skipping.')
        return

    logger.info('Starting metadata pull...')
    client = SFTPClient(
        host=METADATA_SERVER['host'],
        port=METADATA_SERVER['port'],
        username=METADATA_SERVER['username'],
        password=METADATA_SERVER['password'],
        remote_dir=METADATA_SERVER['remote_dir'],
        local_dir=f"{LOCAL_DOWNLOAD_DIR}/metadata"
    )

    downloaded = client.download_all(METADATA_SERVER['files'])
    summary    = run_metadata_sync(downloaded, METADATA_COLUMN_MAP)

    for tech, result in summary.items():
        status = result.get('status', 'error')
        rows   = result.get('upserted', 0)
        msg    = result.get('error') or result.get('reason')
        _log_sync('metadata', tech, status, rows, msg)
        logger.info(f'Metadata [{tech}]: {result}')

    logger.info('Metadata pull complete.')


def start_scheduler():
    """Run DB migrations and start the background scheduler."""
    global _scheduler

    try:
        run_migrations()
    except Exception as e:
        logger.error(f'DB migration failed: {e}')

    from sync_config import PM_PULL_INTERVAL_HOURS, METADATA_PULL_INTERVAL_HOURS

    _scheduler = BackgroundScheduler(daemon=True)

    # Nokia PM — every 2 hours
    _scheduler.add_job(
        pull_nokia_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='nokia_pm_pull',
        name='Nokia PM Pull',
        replace_existing=True
    )

    # Huawei PM — every 2 hours
    _scheduler.add_job(
        pull_huawei_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='huawei_pm_pull',
        name='Huawei PM Pull',
        replace_existing=True
    )

    # Metadata — daily
    _scheduler.add_job(
        pull_metadata,
        trigger=IntervalTrigger(hours=METADATA_PULL_INTERVAL_HOURS),
        id='metadata_pull',
        name='Metadata Pull',
        replace_existing=True
    )

    _scheduler.start()
    logger.info(
        f'Scheduler started — Nokia PM, Huawei PM every {PM_PULL_INTERVAL_HOURS}h, '
        f'Metadata every {METADATA_PULL_INTERVAL_HOURS}h.'
    )


def get_scheduler():
    return _scheduler


def trigger_nokia_pm_now():
    pull_nokia_pm()

def trigger_huawei_pm_now():
    pull_huawei_pm()

def trigger_pm_now():
    """Trigger both vendors at once."""
    pull_nokia_pm()
    pull_huawei_pm()

def trigger_metadata_now():
    pull_metadata()
