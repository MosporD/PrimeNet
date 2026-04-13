"""
Sync Scheduler
==============
Three background jobs:
  nokia_pm_pull   — every 2 h — downloads latest XLSX from each Nokia tech folder
  huawei_pm_pull  — every 2 h — downloads latest archive; ingest like Nokia (2G_Hourly … 5G_Hourly)
  metadata_pull   — daily     — enters newest snapshot folder, downloads all Excel files from each subfolder
"""

import logging
import sqlite3
import os
import glob
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sync.sftp_client import SFTPClient
from sync.pm_processor import (
    run_nokia_pm_sync,
    process_huawei_pm_file,
    clear_nokia_pm_tables,
    apply_pm_retention,
)
from sync.metadata_processor import run_metadata_sync
from sync.db_migration import run_migrations
from sync.group_processor import process_group_file, clear_groups_db

logger = logging.getLogger(__name__)

_scheduler = None
_sync_progress_lock = threading.Lock()
_sync_progress = {
    'nokia_pm': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
    'huawei_pm': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
    'metadata': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
}


def _set_progress(job_key: str, **fields) -> None:
    if job_key not in _sync_progress:
        return
    with _sync_progress_lock:
        cur = dict(_sync_progress[job_key])
        cur.update(fields)
        p = int(cur.get('progress') or 0)
        t = int(cur.get('total') or 0)
        cur['percent'] = int((p * 100 / t)) if t > 0 else (100 if not cur.get('running') else 0)
        cur['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _sync_progress[job_key] = cur


def _start_progress(job_key: str, total: int, message: str) -> None:
    _set_progress(
        job_key,
        running=True,
        stage='running',
        progress=0,
        total=max(0, int(total or 0)),
        message=message,
    )


def _advance_progress(job_key: str, progress: int, message: str | None = None) -> None:
    payload = {'progress': max(0, int(progress or 0))}
    if message is not None:
        payload['message'] = message
    _set_progress(job_key, **payload)


def _finish_progress(job_key: str, ok: bool, message: str) -> None:
    with _sync_progress_lock:
        total = int(_sync_progress[job_key].get('total') or 0)
    _set_progress(
        job_key,
        running=False,
        stage='done' if ok else 'error',
        progress=total,
        message=message,
    )


def get_sync_progress() -> dict:
    with _sync_progress_lock:
        return {k: dict(v) for k, v in _sync_progress.items()}


# ---------------------------------------------------------------------------
# Local download retention (timestamped files accumulate each sync)
# ---------------------------------------------------------------------------

def _prune_sync_download_dir(directory: str, basename_prefix: str, keep: int) -> None:
    """
    Keep the ``keep`` newest files whose names start with ``basename_prefix``;
    remove older ones under ``directory``.
    """
    try:
        if keep < 1 or not directory or not basename_prefix:
            return
        if not os.path.isdir(directory):
            return
        paths = []
        for fn in os.listdir(directory):
            if not fn.startswith(basename_prefix):
                continue
            full = os.path.join(directory, fn)
            if os.path.isfile(full):
                paths.append(full)
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old in paths[keep:]:
            try:
                os.unlink(old)
                logger.info('Pruned old sync download: %s', old)
            except OSError as ex:
                logger.warning('Could not remove %s: %s', old, ex)
    except Exception as ex:
        logger.warning('Prune %s (%s*): %s', directory, basename_prefix, ex)


# ---------------------------------------------------------------------------
# Sync log helper
# ---------------------------------------------------------------------------

def _log_sync(sync_type, technology, status, rows=0, message=None):
    try:
        # Always use the canonical app DB path (works regardless of CWD).
        from sync_config import NCMUSERS_DB
        conn = sqlite3.connect(NCMUSERS_DB)
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
        NOKIA_PM_SERVER,
        LOCAL_DOWNLOAD_DIR,
        SYNC_DOWNLOAD_KEEP_FILES,
        NOKIA_PM_DB,
        PM_SYNC_FULL_CLEAR,
        PM_RETENTION_DAYS,
    )
    from sync.metadata_processor import seed_pm_cells_to_metadata

    host = NOKIA_PM_SERVER['host']
    if not host:
        logger.warning('Nokia PM server not configured.')
        _finish_progress('nokia_pm', False, 'Server not configured.')
        return

    logger.info('Starting Nokia PM pull...')
    pm_nokia_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_nokia')
    descend = NOKIA_PM_SERVER.get('descend_into_newest_subdir', True)
    excel_exts = ('.xlsx', '.xls', '.xlsm', '.csv', '.zip')

    def _download_nokia_tech(pair):
        tech, remote_dir = pair
        client = SFTPClient(
            host=host,
            port=NOKIA_PM_SERVER['port'],
            username=NOKIA_PM_SERVER['username'],
            password=NOKIA_PM_SERVER['password'],
            local_dir=pm_nokia_dir,
        )
        try:
            local_path = client.download_latest_xlsx(
                remote_dir,
                prefix=f'nokia_{tech}_',
                descend_into_newest_subdir=descend,
                excel_exts=excel_exts,
            )
            if not local_path:
                search_glob = os.path.join(pm_nokia_dir, f'nokia_{tech}_*')
                candidates = [
                    p for p in glob.glob(search_glob)
                    if os.path.isfile(p)
                    and p.lower().endswith(('.xlsx', '.xls', '.xlsm', '.csv', '.zip'))
                ]
                if candidates:
                    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    local_path = candidates[0]
                    logger.warning(
                        'Nokia PM [%s]: download failed, using latest local fallback: %s',
                        tech,
                        local_path,
                    )
            return tech, local_path
        except Exception:
            logger.exception('Nokia PM [%s]: download failed', tech)
            return tech, None

    try:
        items = list(NOKIA_PM_SERVER.get('dirs', {}).items())
        _start_progress('nokia_pm', max(1, len(items)), f'Downloading {len(items)} technology file(s)...')
        n_workers = max(1, min(len(items), 4))
        downloaded = {}
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            future_map = {pool.submit(_download_nokia_tech, p): p[0] for p in items}
            done_downloads = 0
            for fut in as_completed(future_map):
                tech_key = future_map[fut]
                try:
                    tech, local_path = fut.result()
                    downloaded[tech] = local_path
                except Exception:
                    logger.exception('Nokia PM [%s]: worker failed', tech_key)
                    downloaded[tech_key] = None
                done_downloads += 1
                _advance_progress('nokia_pm', done_downloads, f'Downloaded {done_downloads}/{len(items)} technology file(s).')

        if not any(downloaded.values()):
            logger.error('Nokia PM: no files downloaded and no local fallback available.')
            _log_sync('pm_nokia', 'all', 'error', 0, 'Download failed')
            _finish_progress('nokia_pm', False, 'No files downloaded.')
            return

        # Full refresh wipes tables; incremental keeps rows and only upserts from files.
        if PM_SYNC_FULL_CLEAR:
            clear_nokia_pm_tables()
        else:
            logger.info('Nokia PM: incremental sync (PM_SYNC_MODE) — skipping full table clear.')

        _start_progress('nokia_pm', max(1, len(downloaded)), f'Inserting data for {len(downloaded)} technology file(s)...')
        summary = run_nokia_pm_sync(downloaded)
        done_insert = 0
        for tech, result in summary.items():
            status = result.get('status', 'error')
            rows   = result.get('inserted', result.get('upserted', 0))
            msg    = result.get('error') or result.get('reason')
            _log_sync('pm_nokia', tech, status, rows, msg)
            logger.info(f'Nokia PM [{tech}]: {result}')
            done_insert += 1
            _advance_progress('nokia_pm', done_insert, f'Inserted {done_insert}/{len(downloaded)} technologies.')

        if PM_RETENTION_DAYS > 0:
            try:
                apply_pm_retention(NOKIA_PM_DB, PM_RETENTION_DAYS)
            except Exception:
                logger.exception('Nokia PM retention (PM_RETENTION_DAYS) failed')

        seed_pm_cells_to_metadata(NOKIA_PM_DB, 'Nokia')
        logger.info('Nokia PM pull complete.')
        _finish_progress('nokia_pm', True, 'Nokia PM sync completed.')
    except Exception as e:
        logger.exception('Nokia PM pull failed: %s', e)
        _log_sync('pm_nokia', 'all', 'error', 0, str(e))
        _finish_progress('nokia_pm', False, f'Nokia PM sync failed: {e}')
    finally:
        for tech in NOKIA_PM_SERVER.get('dirs', {}):
            _prune_sync_download_dir(pm_nokia_dir, f'nokia_{tech}_', SYNC_DOWNLOAD_KEEP_FILES)


# ---------------------------------------------------------------------------
# Huawei PM — single folder, single file with 3 sheets (2G/3G/4G)
# ---------------------------------------------------------------------------

def pull_huawei_pm():
    from sync_config import (
        HUAWEI_PM_SERVER,
        LOCAL_DOWNLOAD_DIR,
        SYNC_DOWNLOAD_KEEP_FILES,
        HUAWEI_PM_DB,
        PM_RETENTION_DAYS,
    )
    from sync.metadata_processor import seed_pm_cells_to_metadata

    host = HUAWEI_PM_SERVER['host']
    if not host:
        logger.warning('Huawei PM server not configured.')
        _finish_progress('huawei_pm', False, 'Server not configured.')
        return

    logger.info('Starting Huawei PM pull...')
    pm_huawei_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'pm_huawei')
    client = SFTPClient(
        host=host,
        port=HUAWEI_PM_SERVER['port'],
        username=HUAWEI_PM_SERVER['username'],
        password=HUAWEI_PM_SERVER['password'],
        local_dir=pm_huawei_dir,
    )

    try:
        _start_progress('huawei_pm', 1, 'Downloading Huawei PM file...')
        local_path = client.download_latest_xlsx(
            HUAWEI_PM_SERVER['remote_dir'],
            prefix='huawei_all_',
            descend_into_newest_subdir=HUAWEI_PM_SERVER.get(
                'descend_into_newest_subdir', True
            ),
            # Huawei PRS exports are sometimes CSV/XLSM even when "Performance" jobs are Excel-like.
            excel_exts=('.xlsx', '.xls', '.xlsm', '.csv', '.zip'),
        )

        if not local_path:
            # Fallback: use the latest locally downloaded Huawei file if SFTP pull fails.
            import glob
            search_glob = os.path.join(pm_huawei_dir, '*')
            candidates = [
                p for p in glob.glob(search_glob)
                if os.path.isfile(p)
                and p.lower().endswith(('.xlsx', '.xls', '.xlsm', '.csv', '.zip'))
            ]
            if candidates:
                candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                local_path = candidates[0]
                logger.warning(
                    'Huawei PM: download failed, using latest local file fallback: %s',
                    local_path,
                )
            else:
                logger.error('Huawei PM: no file downloaded and no local fallback available.')
                _log_sync('pm_huawei', 'all', 'error', 0, 'Download failed')
                _finish_progress('huawei_pm', False, 'No Huawei PM file downloaded.')
                return

        _advance_progress('huawei_pm', 1, 'Download complete. Processing PM data...')
        summary = process_huawei_pm_file(local_path)
        total_parts = max(1, len(summary))
        _set_progress('huawei_pm', total=1 + total_parts)
        done_parts = 0
        for tech, result in summary.items():
            status = result.get('status', 'error')
            rows   = result.get('inserted', result.get('upserted', 0))
            msg    = result.get('error') or result.get('reason')
            _log_sync('pm_huawei', tech, status, rows, msg)
            logger.info(f'Huawei PM [{tech}]: {result}')
            done_parts += 1
            _advance_progress('huawei_pm', 1 + done_parts, f'Processed {done_parts}/{total_parts} technology outputs.')

        if PM_RETENTION_DAYS > 0:
            try:
                apply_pm_retention(HUAWEI_PM_DB, PM_RETENTION_DAYS)
            except Exception:
                logger.exception('Huawei PM retention (PM_RETENTION_DAYS) failed')

        seed_pm_cells_to_metadata(HUAWEI_PM_DB, 'Huawei')
        logger.info('Huawei PM pull complete.')
        _finish_progress('huawei_pm', True, 'Huawei PM sync completed.')
    except Exception as e:
        logger.exception('Huawei PM pull failed: %s', e)
        _log_sync('pm_huawei', 'all', 'error', 0, str(e))
        _finish_progress('huawei_pm', False, f'Huawei PM sync failed: {e}')
    finally:
        _prune_sync_download_dir(pm_huawei_dir, 'huawei_all_', SYNC_DOWNLOAD_KEEP_FILES)


# ---------------------------------------------------------------------------
# Metadata — root dir has dated snapshot folders; enter newest, pull 5 files
# ---------------------------------------------------------------------------

def pull_metadata():
    from sync_config import METADATA_SERVER, LOCAL_DOWNLOAD_DIR, SYNC_DOWNLOAD_KEEP_FILES

    host = METADATA_SERVER['host']
    if not host:
        logger.warning('Metadata server not configured.')
        _finish_progress('metadata', False, 'Server not configured.')
        return

    logger.info('Starting Metadata pull...')
    meta_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'metadata')
    client = SFTPClient(
        host=host,
        port=METADATA_SERVER['port'],
        username=METADATA_SERVER['username'],
        password=METADATA_SERVER['password'],
        local_dir=meta_dir,
    )

    try:
        _start_progress('metadata', 1, 'Downloading metadata snapshots...')
        # Enter the latest dated snapshot folder and download the CSV files
        # that sit directly at its first level (skip any inner sub-subfolders
        # such as "Atoll Files/").
        downloaded = client.download_files_from_latest_subdir(
            root_dir=METADATA_SERVER['root_dir'],
            prefix='meta_',
        )

        _advance_progress('metadata', 1, 'Download complete. Processing metadata files...')
        summary = run_metadata_sync(downloaded)
        total_parts = max(1, len(summary))
        _set_progress('metadata', total=1 + total_parts)
        done_parts = 0
        for tech, result in summary.items():
            status = result.get('status', 'error')
            rows   = result.get('upserted', 0)
            msg    = result.get('error') or result.get('reason')
            _log_sync('metadata', tech, status, rows, msg)
            logger.info(f'Metadata [{tech}]: {result}')
            done_parts += 1
            _advance_progress('metadata', 1 + done_parts, f'Processed {done_parts}/{total_parts} technologies.')

        logger.info('Metadata pull complete.')
        _finish_progress('metadata', True, 'Metadata sync completed.')
    except Exception as e:
        logger.exception('Metadata pull failed: %s', e)
        _log_sync('metadata', 'all', 'error', 0, str(e))
        _finish_progress('metadata', False, f'Metadata sync failed: {e}')
    finally:
        _prune_sync_download_dir(meta_dir, 'meta_', SYNC_DOWNLOAD_KEEP_FILES)


# ---------------------------------------------------------------------------
# Groups (Nokia/Huawei)
# ---------------------------------------------------------------------------

def pull_nokia_groups():
    from sync_config import NOKIA_GROUPS_SERVER, LOCAL_DOWNLOAD_DIR, SYNC_DOWNLOAD_KEEP_FILES

    host = NOKIA_GROUPS_SERVER['host']
    if not host:
        logger.warning('Nokia Groups server not configured.')
        return

    logger.info('Starting Nokia Groups pull...')
    groups_nokia_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'groups_nokia')
    client = SFTPClient(
        host=host,
        port=NOKIA_GROUPS_SERVER['port'],
        username=NOKIA_GROUPS_SERVER['username'],
        password=NOKIA_GROUPS_SERVER['password'],
        local_dir=groups_nokia_dir,
    )

    try:
        clear_groups_db('Nokia')
        downloaded = {}
        descend = NOKIA_GROUPS_SERVER.get('descend_into_newest_subdir', True)
        for tech, remote_dir in NOKIA_GROUPS_SERVER['dirs'].items():
            downloaded[tech] = client.download_latest_xlsx(
                remote_dir,
                prefix=f'nokia_group_{tech}_',
                descend_into_newest_subdir=descend,
                excel_exts=('.xlsx', '.xls', '.xlsm', '.csv', '.zip'),
            )
        for tech, path in downloaded.items():
            if not path:
                _log_sync('groups_nokia', tech, 'skipped', 0, 'Download failed')
                continue
            result = process_group_file(path, 'Nokia', default_technology=tech)
            _log_sync('groups_nokia', tech, result.get('status', 'error'), result.get('inserted', 0), result.get('error') or result.get('reason'))
    except Exception as e:
        logger.exception('Nokia Groups pull failed: %s', e)
        _log_sync('groups_nokia', 'all', 'error', 0, str(e))
    finally:
        for tech in NOKIA_GROUPS_SERVER.get('dirs', {}):
            _prune_sync_download_dir(groups_nokia_dir, f'nokia_group_{tech}_', SYNC_DOWNLOAD_KEEP_FILES)


def pull_huawei_groups():
    from sync_config import HUAWEI_GROUPS_SERVER, LOCAL_DOWNLOAD_DIR, SYNC_DOWNLOAD_KEEP_FILES

    host = HUAWEI_GROUPS_SERVER['host']
    if not host:
        logger.warning('Huawei Groups server not configured.')
        return

    logger.info('Starting Huawei Groups pull...')
    groups_huawei_dir = os.path.join(LOCAL_DOWNLOAD_DIR, 'groups_huawei')
    client = SFTPClient(
        host=host,
        port=HUAWEI_GROUPS_SERVER['port'],
        username=HUAWEI_GROUPS_SERVER['username'],
        password=HUAWEI_GROUPS_SERVER['password'],
        local_dir=groups_huawei_dir,
    )
    try:
        clear_groups_db('Huawei')
        local_path = client.download_latest_xlsx(
            HUAWEI_GROUPS_SERVER['remote_dir'],
            prefix='huawei_group_',
            descend_into_newest_subdir=HUAWEI_GROUPS_SERVER.get('descend_into_newest_subdir', True),
            excel_exts=('.xlsx', '.xls', '.xlsm', '.csv', '.zip'),
        )
        if not local_path:
            _log_sync('groups_huawei', 'all', 'skipped', 0, 'Download failed')
            return
        result = process_group_file(local_path, 'Huawei')
        _log_sync('groups_huawei', 'all', result.get('status', 'error'), result.get('inserted', 0), result.get('error') or result.get('reason'))
    except Exception as e:
        logger.exception('Huawei Groups pull failed: %s', e)
        _log_sync('groups_huawei', 'all', 'error', 0, str(e))
    finally:
        _prune_sync_download_dir(groups_huawei_dir, 'huawei_group_', SYNC_DOWNLOAD_KEEP_FILES)


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

    # next_run_time=datetime.now() makes each job run immediately on startup
    # (then repeat on the interval).
    _scheduler.add_job(
        pull_nokia_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='nokia_pm_pull',
        name='Nokia PM Pull',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.add_job(
        pull_huawei_pm,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='huawei_pm_pull',
        name='Huawei PM Pull',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.add_job(
        pull_nokia_groups,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='nokia_groups_pull',
        name='Nokia Groups Pull',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.add_job(
        pull_huawei_groups,
        trigger=IntervalTrigger(hours=PM_PULL_INTERVAL_HOURS),
        id='huawei_groups_pull',
        name='Huawei Groups Pull',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.add_job(
        pull_metadata,
        trigger=IntervalTrigger(hours=METADATA_PULL_INTERVAL_HOURS),
        id='metadata_pull',
        name='Metadata Pull',
        replace_existing=True,
        next_run_time=datetime.now()
    )

    _scheduler.start()
    logger.info(
        f'Scheduler started — Nokia PM + Huawei PM every {PM_PULL_INTERVAL_HOURS}h, '
        f'Metadata every {METADATA_PULL_INTERVAL_HOURS}h. '
        f'First pull running now.'
    )


def get_scheduler():
    return _scheduler

# Manual trigger helpers
def trigger_nokia_pm_now():  pull_nokia_pm()
def trigger_huawei_pm_now(): pull_huawei_pm()
def trigger_pm_now():        pull_nokia_pm(); pull_huawei_pm()
def trigger_metadata_now():  pull_metadata()
def trigger_nokia_groups_now(): pull_nokia_groups()
def trigger_huawei_groups_now(): pull_huawei_groups()
