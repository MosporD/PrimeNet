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
import subprocess
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

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


def pull_all_raw_master():
    """Run scripts/pull_all_raw.py (clear + pull Huawei/Nokia/Metadata raw files)."""
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'pull_all_raw.py')
    if not os.path.isfile(script):
        logger.error('Raw master launcher not found: %s', script)
        _log_sync('raw_master_pull', 'all', 'error', 0, f'missing script: {script}')
        return
    try:
        logger.info('Starting raw master pull launcher: %s', script)
        proc = subprocess.run(
            [sys.executable, script],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            logger.info('raw master stdout:\n%s', proc.stdout.strip())
        if proc.stderr:
            logger.warning('raw master stderr:\n%s', proc.stderr.strip())
        if proc.returncode == 0:
            _log_sync('raw_master_pull', 'all', 'ok', 0, 'Master raw pull completed')
            logger.info('Raw master pull completed successfully.')
        else:
            details = ''
            try:
                out_lines = [ln.strip() for ln in (proc.stdout or '').splitlines() if ln.strip()]
                err_lines = [ln.strip() for ln in (proc.stderr or '').splitlines() if ln.strip()]
                # Keep concise but actionable reason in sync history.
                if err_lines:
                    details = err_lines[-1]
                elif out_lines:
                    run_lines = [ln for ln in out_lines if ln.startswith('[run]')]
                    details = run_lines[-1] if run_lines else out_lines[-1]
            except Exception:
                details = ''
            msg = f'Master raw pull failed (code={proc.returncode})'
            if details:
                msg = f'{msg}: {details[:350]}'
            _log_sync('raw_master_pull', 'all', 'error', 0, msg)
            logger.error('Raw master pull failed with code %s.', proc.returncode)
    except Exception as e:
        _log_sync('raw_master_pull', 'all', 'error', 0, str(e))
        logger.exception('Raw master pull failed: %s', e)


def _all_table_row_counts(db_path: str) -> dict[str, int]:
    if not os.path.isfile(db_path):
        return {}
    out: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (tbl,) in tables:
            try:
                n = cur.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                out[str(tbl)] = int(n or 0)
            except Exception:
                # Skip objects that are not normal row tables.
                continue
    finally:
        conn.close()
    return out


def _extract_technology_key(table_name: str) -> str:
    low = (table_name or '').lower()
    if '4g_tdd' in low:
        return '4G-TDD'
    if '4g_fdd' in low:
        return '4G-FDD'
    if re.search(r'(^|[^0-9a-z])5g([^0-9a-z]|$)', low):
        return '5G'
    if re.search(r'(^|[^0-9a-z])4g([^0-9a-z]|$)', low):
        return '4G'
    if re.search(r'(^|[^0-9a-z])3g([^0-9a-z]|$)', low):
        return '3G'
    if re.search(r'(^|[^0-9a-z])2g([^0-9a-z]|$)', low):
        return '2G'
    return 'all'


def _log_loader_row_deltas(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]) -> None:
    """Write per vendor/tech row deltas to sync_log after loader execution."""
    bucket: dict[tuple[str, str], int] = {}
    for db_label, after_counts in after.items():
        before_counts = before.get(db_label, {})
        for tbl, after_n in after_counts.items():
            delta = int(after_n or 0) - int(before_counts.get(tbl, 0) or 0)
            if delta <= 0:
                continue
            tech = _extract_technology_key(tbl)
            key = (db_label, tech)
            bucket[key] = bucket.get(key, 0) + delta

    if not bucket:
        _log_sync('db_loader', 'all', 'ok', 0, 'No positive row deltas detected')
        return

    for (db_label, tech), delta in sorted(bucket.items()):
        _log_sync('db_loader', f'{db_label}:{tech}', 'ok', int(delta), 'Rows added by loader')


def run_full_sync_cycle():
    """End-to-end cycle: raw pull + DB loader + per vendor/tech row-delta logs."""
    from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, NOKIA_GROUPS_DB, HUAWEI_GROUPS_DB, METADATA_DB

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loader_script = os.path.join(project_root, 'scripts', 'load_raw_csv_to_databases.py')

    before = {
        'nokia_pm': _all_table_row_counts(NOKIA_PM_DB),
        'huawei_pm': _all_table_row_counts(HUAWEI_PM_DB),
        'nokia_groups': _all_table_row_counts(NOKIA_GROUPS_DB),
        'huawei_groups': _all_table_row_counts(HUAWEI_GROUPS_DB),
        'metadata': _all_table_row_counts(METADATA_DB),
    }

    pull_all_raw_master()

    if not os.path.isfile(loader_script):
        _log_sync('db_loader', 'all', 'error', 0, f'missing script: {loader_script}')
        logger.error('DB loader script not found: %s', loader_script)
        return

    try:
        logger.info('Starting DB loader script: %s', loader_script)
        proc = subprocess.run(
            [sys.executable, loader_script],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            logger.info('db loader stdout:\n%s', proc.stdout.strip())
        if proc.stderr:
            logger.warning('db loader stderr:\n%s', proc.stderr.strip())

        if proc.returncode != 0:
            _log_sync('db_loader', 'all', 'error', 0, f'Loader failed (code={proc.returncode})')
            logger.error('DB loader failed with code %s', proc.returncode)
            return

        neighbor_loader = os.path.join(project_root, 'scripts', 'load_nokia_neighbor_raw_to_db.py')
        if os.path.isfile(neighbor_loader):
            nproc = subprocess.run(
                [sys.executable, neighbor_loader],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if nproc.stdout:
                logger.info('neighbor loader stdout:\n%s', nproc.stdout.strip())
            if nproc.stderr:
                logger.warning('neighbor loader stderr:\n%s', nproc.stderr.strip())
            if nproc.returncode != 0:
                logger.warning('Neighbor raw loader failed with code %s', nproc.returncode)

        after = {
            'nokia_pm': _all_table_row_counts(NOKIA_PM_DB),
            'huawei_pm': _all_table_row_counts(HUAWEI_PM_DB),
            'nokia_groups': _all_table_row_counts(NOKIA_GROUPS_DB),
            'huawei_groups': _all_table_row_counts(HUAWEI_GROUPS_DB),
            'metadata': _all_table_row_counts(METADATA_DB),
        }
        _log_loader_row_deltas(before, after)
        logger.info('Full sync cycle completed successfully.')
    except Exception as e:
        _log_sync('db_loader', 'all', 'error', 0, str(e))
        logger.exception('Full sync cycle failed during DB load: %s', e)


def run_daily_sync_cycle():
    """End-to-end DAILY cycle: daily raw pull + daily DB load."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(project_root, 'scripts', 'pull_and_load_daily.py')
    if not os.path.isfile(script):
        _log_sync('daily_full_sync', 'all', 'error', 0, f'missing script: {script}')
        logger.error('Daily pipeline script not found: %s', script)
        return
    try:
        proc = subprocess.run([sys.executable, script], cwd=project_root, capture_output=True, text=True)
        if proc.stdout:
            logger.info('daily full sync stdout:\n%s', proc.stdout.strip())
        if proc.stderr:
            logger.warning('daily full sync stderr:\n%s', proc.stderr.strip())
        if proc.returncode == 0:
            _log_sync('daily_full_sync', 'all', 'ok', 0, 'Daily full sync completed')
            logger.info('Daily full sync completed successfully.')
        else:
            _log_sync('daily_full_sync', 'all', 'error', 0, f'Daily full sync failed (code={proc.returncode})')
            logger.error('Daily full sync failed with code %s.', proc.returncode)
    except Exception as e:
        _log_sync('daily_full_sync', 'all', 'error', 0, str(e))
        logger.exception('Daily full sync failed: %s', e)


def run_manual_category_sync(category: str):
    """
    Run manual category sync:
      cells-hourly | groups-hourly | cells-daily | groups-daily
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pull_script = 'pull_all_raw.py'
    load_args = ['--scope', 'hourly']
    sync_type = category.replace('-', '_')
    if category.endswith('daily'):
        pull_script = 'pull_all_raw_daily.py'
        load_args = ['--scope', 'daily', '--skip-kpi-db']
    if category.startswith('cells-'):
        load_args.extend(['--category', 'cells'])
    elif category.startswith('groups-'):
        load_args.extend(['--category', 'groups'])
    else:
        _log_sync('manual_category_sync', category, 'error', 0, 'Unknown category')
        return

    pull_path = os.path.join(project_root, 'scripts', pull_script)
    load_path = os.path.join(project_root, 'scripts', 'load_raw_csv_to_databases.py')
    if not os.path.isfile(pull_path) or not os.path.isfile(load_path):
        _log_sync('manual_category_sync', category, 'error', 0, 'Required script missing')
        return

    try:
        pull_proc = subprocess.run([sys.executable, pull_path], cwd=project_root, capture_output=True, text=True)
        if pull_proc.stdout:
            logger.info('%s pull stdout:\n%s', category, pull_proc.stdout.strip())
        if pull_proc.stderr:
            logger.warning('%s pull stderr:\n%s', category, pull_proc.stderr.strip())
        if pull_proc.returncode != 0:
            _log_sync(sync_type, 'all', 'error', 0, f'pull failed (code={pull_proc.returncode})')
            return

        load_proc = subprocess.run([sys.executable, load_path] + load_args, cwd=project_root, capture_output=True, text=True)
        if load_proc.stdout:
            logger.info('%s load stdout:\n%s', category, load_proc.stdout.strip())
        if load_proc.stderr:
            logger.warning('%s load stderr:\n%s', category, load_proc.stderr.strip())
        if load_proc.returncode == 0:
            _log_sync(sync_type, 'all', 'ok', 0, 'Manual category sync completed')
        else:
            _log_sync(sync_type, 'all', 'error', 0, f'load failed (code={load_proc.returncode})')
    except Exception as e:
        _log_sync(sync_type, 'all', 'error', 0, str(e))
        logger.exception('Manual category sync failed (%s): %s', category, e)


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
    _finish_progress('nokia_pm', True, 'Reset mode: Nokia PM pull disabled.')
    logger.info('Reset mode: pull_nokia_pm is disabled.')
    return
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
    _finish_progress('huawei_pm', True, 'Reset mode: Huawei PM pull disabled.')
    logger.info('Reset mode: pull_huawei_pm is disabled.')
    return
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
    _finish_progress('metadata', True, 'Reset mode: Metadata pull disabled.')
    logger.info('Reset mode: pull_metadata is disabled.')
    return
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
    logger.info('Reset mode: pull_nokia_groups is disabled.')
    return
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


def run_remote_pull_watcher_once():
    """
    One cycle of scripts/watch_remote_new_files_and_pull.py (--once): probe remotes,
    pull+load only when signatures change (state in databases/admin/pull_watch_state.json).
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, 'scripts', 'watch_remote_new_files_and_pull.py')
    if not os.path.isfile(script):
        logger.warning('Remote pull watcher script not found: %s', script)
        return
    try:
        logger.info('Starting remote pull watcher (--once)...')
        proc = subprocess.run(
            [sys.executable, script, '--once'],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            out = proc.stdout.strip()
            if out:
                logger.info('pull watcher stdout:\n%s', out[:12000])
        if proc.stderr:
            err = proc.stderr.strip()
            if err:
                logger.warning('pull watcher stderr:\n%s', err[:12000])
        if proc.returncode != 0:
            logger.error('Remote pull watcher exited with code %s', proc.returncode)
        else:
            logger.info('Remote pull watcher cycle completed.')
    except Exception as e:
        logger.exception('Remote pull watcher failed: %s', e)


def pull_huawei_groups():
    logger.info('Reset mode: pull_huawei_groups is disabled.')
    return
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

    from sync_config import (
        RAW_PULL_INTERVAL_HOURS,
        DAILY_PULL_HOUR,
        PULL_WATCHER_POLL_INTERVAL_SEC,
    )

    _scheduler = BackgroundScheduler(daemon=True)

    # Run immediately on startup, then every configured interval.
    _scheduler.add_job(
        run_full_sync_cycle,
        trigger=IntervalTrigger(hours=RAW_PULL_INTERVAL_HOURS),
        id='raw_master_pull',
        name='Raw + DB Full Sync',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    _scheduler.add_job(
        run_daily_sync_cycle,
        trigger=CronTrigger(hour=DAILY_PULL_HOUR, minute=0),
        id='daily_full_sync_7am',
        name='Daily Raw + DB Full Sync',
        replace_existing=True,
    )

    # Remote signature watcher (conditional pulls; not the same as full raw master sync).
    if os.environ.get('NCM_DISABLE_PULL_WATCHER', '').strip().lower() not in ('1', 'true', 'yes'):
        _scheduler.add_job(
            run_remote_pull_watcher_once,
            trigger=IntervalTrigger(seconds=int(PULL_WATCHER_POLL_INTERVAL_SEC)),
            id='remote_pull_signature_watcher',
            name='Remote SFTP signature watch + selective pull',
            replace_existing=True,
            next_run_time=datetime.now(),
            coalesce=True,
            max_instances=1,
        )

    _scheduler.start()
    _watcher_on = os.environ.get('NCM_DISABLE_PULL_WATCHER', '').strip().lower() not in ('1', 'true', 'yes')
    if _watcher_on:
        logger.info(
            'Scheduler started — raw master every %sh, daily at %02d:00, pull watcher every %ss.',
            RAW_PULL_INTERVAL_HOURS,
            DAILY_PULL_HOUR,
            PULL_WATCHER_POLL_INTERVAL_SEC,
        )
    else:
        logger.info(
            'Scheduler started — raw master every %sh, daily at %02d:00 (pull watcher disabled).',
            RAW_PULL_INTERVAL_HOURS,
            DAILY_PULL_HOUR,
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
def trigger_raw_master_now(): run_full_sync_cycle()
def trigger_daily_full_now(): run_daily_sync_cycle()
def trigger_cells_hourly_now(): run_manual_category_sync('cells-hourly')
def trigger_groups_hourly_now(): run_manual_category_sync('groups-hourly')
def trigger_cells_daily_now(): run_manual_category_sync('cells-daily')
def trigger_groups_daily_now(): run_manual_category_sync('groups-daily')
