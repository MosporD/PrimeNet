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

from .sftp_client import SFTPClient
from .pm_processor import (
    run_nokia_pm_sync,
    process_huawei_pm_file,
    clear_nokia_pm_tables,
    apply_pm_retention,
)
from .metadata_processor import run_metadata_sync
from .db_migration import run_migrations
from .group_processor import process_group_file, clear_groups_db

logger = logging.getLogger(__name__)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_scheduler = None
_scheduler_mode_summary = {
    'mode': 'unknown',
    'watcher_primary': False,
    'legacy_enabled': False,
    'watcher_enabled': False,
    'scheduled_ingest_enabled': False,
    'raw_pull_interval_hours': None,
    'daily_pull_hour': None,
    'watcher_poll_interval_sec': None,
}
_sync_progress_lock = threading.Lock()
_pipeline_cycle_lock = threading.Lock()
_sync_progress = {
    'nokia_pm': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
    'huawei_pm': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
    'metadata': {'running': False, 'stage': 'idle', 'progress': 0, 'total': 0, 'percent': 0, 'message': '', 'updated_at': None},
}


def pull_all_raw_master():
    """Run scripts/pull_all_raw.py (clear + pull Huawei/Nokia/Metadata raw files)."""
    script = os.path.join(_PROJECT_ROOT, 'scripts', 'pull_all_raw.py')
    if not os.path.isfile(script):
        logger.error('Raw master launcher not found: %s', script)
        _log_sync('raw_master_pull', 'all', 'error', 0, f'missing script: {script}')
        return
    try:
        logger.info('Starting raw master pull launcher: %s', script)
        proc = subprocess.run(
            [sys.executable, script],
            cwd=_PROJECT_ROOT,
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


def _subprocess_failure_detail(proc: subprocess.CompletedProcess, *, max_len: int = 350) -> str:
    """Last actionable line from child stdout/stderr for sync_log."""
    try:
        err_lines = [ln.strip() for ln in (proc.stderr or '').splitlines() if ln.strip()]
        out_lines = [ln.strip() for ln in (proc.stdout or '').splitlines() if ln.strip()]
        if err_lines:
            for ln in reversed(err_lines):
                if 'Error' in ln or 'error' in ln or 'failed' in ln or 'Traceback' in ln:
                    return ln[:max_len]
            return err_lines[-1][:max_len]
        if out_lines:
            for ln in reversed(out_lines):
                if 'failed' in ln.lower() or 'error' in ln.lower():
                    return ln[:max_len]
            return out_lines[-1][:max_len]
    except Exception:
        pass
    return ''


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
    """End-to-end cycle via canonical hourly orchestrator."""
    from sync_config import NOKIA_PM_DB, HUAWEI_PM_DB, NOKIA_GROUPS_DB, HUAWEI_GROUPS_DB, METADATA_DB

    project_root = _PROJECT_ROOT
    orchestrator = os.path.join(project_root, 'pipeline', 'orchestrators', 'orchestrate_hourly_full.py')

    before = {
        'nokia_pm': _all_table_row_counts(NOKIA_PM_DB),
        'huawei_pm': _all_table_row_counts(HUAWEI_PM_DB),
        'nokia_groups': _all_table_row_counts(NOKIA_GROUPS_DB),
        'huawei_groups': _all_table_row_counts(HUAWEI_GROUPS_DB),
        'metadata': _all_table_row_counts(METADATA_DB),
    }

    if not os.path.isfile(orchestrator):
        _log_sync('db_loader', 'all', 'error', 0, f'missing script: {orchestrator}')
        logger.error('Hourly orchestrator script not found: %s', orchestrator)
        return

    if not _pipeline_cycle_lock.acquire(blocking=False):
        msg = 'Hourly orchestrator skipped: another pipeline cycle is already running'
        _log_sync('db_loader', 'all', 'error', 0, msg)
        logger.warning(msg)
        return

    try:
        logger.info('Starting hourly orchestrator script: %s', orchestrator)
        proc = subprocess.run(
            [sys.executable, orchestrator],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            logger.info('db loader stdout:\n%s', proc.stdout.strip())
        if proc.stderr:
            logger.warning('db loader stderr:\n%s', proc.stderr.strip())

        # code=2 => partial pull (one vendor failed) but the load still ran on
        # whatever arrived. Record it as a visible warning, not a hard failure.
        partial = proc.returncode == 2
        if proc.returncode not in (0, 2):
            details = _subprocess_failure_detail(proc)
            msg = f'Hourly orchestrator failed (code={proc.returncode})'
            if details:
                msg = f'{msg}: {details}'
            _log_sync('db_loader', 'all', 'error', 0, msg)
            logger.error('Hourly orchestrator failed with code %s', proc.returncode)
            return

        if partial:
            details = _subprocess_failure_detail(proc)
            msg = 'Hourly orchestrator partial: some vendors failed to pull'
            if details:
                msg = f'{msg}: {details}'
            _log_sync('db_loader', 'all', 'error', 0, msg)
            logger.warning(msg)

        after = {
            'nokia_pm': _all_table_row_counts(NOKIA_PM_DB),
            'huawei_pm': _all_table_row_counts(HUAWEI_PM_DB),
            'nokia_groups': _all_table_row_counts(NOKIA_GROUPS_DB),
            'huawei_groups': _all_table_row_counts(HUAWEI_GROUPS_DB),
            'metadata': _all_table_row_counts(METADATA_DB),
        }
        _log_loader_row_deltas(before, after)
        logger.info('Full sync cycle completed%s.', ' (partial pull)' if partial else ' successfully')
    except Exception as e:
        _log_sync('db_loader', 'all', 'error', 0, str(e))
        logger.exception('Full sync cycle failed during DB load: %s', e)
    finally:
        _pipeline_cycle_lock.release()


def run_daily_sync_cycle():
    """End-to-end DAILY cycle: daily raw pull + daily DB load."""
    project_root = _PROJECT_ROOT
    script = os.path.join(project_root, 'pipeline', 'orchestrators', 'orchestrate_daily_full.py')
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
    project_root = _PROJECT_ROOT
    pull_script = os.path.join('pipeline', 'pull', 'hourly', 'pull_all.py')
    load_script = os.path.join('pipeline', 'load', 'hourly', 'load_all.py')
    pull_args: list[str] = []
    load_args: list[str] = []
    is_daily = False
    sync_type = category.replace('-', '_')
    if category.endswith('daily'):
        pull_script = os.path.join('pipeline', 'pull', 'daily', 'pull_all.py')
        load_script = os.path.join('pipeline', 'load', 'daily', 'load_all.py')
        is_daily = True
    if category.startswith('cells-'):
        pull_args.extend(['--category', 'cells'])
        load_args.extend(['--category', 'cells'])
    elif category.startswith('groups-'):
        pull_args.extend(['--category', 'groups'])
        load_args.extend(['--category', 'groups'])
    else:
        _log_sync('manual_category_sync', category, 'error', 0, 'Unknown category')
        return

    pull_path = os.path.join(project_root, pull_script)
    load_path = os.path.join(project_root, load_script)
    if not os.path.isfile(pull_path) or not os.path.isfile(load_path):
        _log_sync('manual_category_sync', category, 'error', 0, 'Required script missing')
        return

    try:
        pull_proc = subprocess.run([sys.executable, pull_path] + pull_args, cwd=project_root, capture_output=True, text=True)
        if pull_proc.stdout:
            logger.info('%s pull stdout:\n%s', category, pull_proc.stdout.strip())
        if pull_proc.stderr:
            logger.warning('%s pull stderr:\n%s', category, pull_proc.stderr.strip())
        # code=2 => partial pull (one vendor failed); still load whatever arrived.
        pull_partial = pull_proc.returncode == 2
        if pull_proc.returncode not in (0, 2):
            details = _subprocess_failure_detail(pull_proc)
            msg = f'pull failed (code={pull_proc.returncode})'
            if details:
                msg = f'{msg}: {details}'
            _log_sync(sync_type, 'all', 'error', 0, msg)
            return
        if pull_partial:
            details = _subprocess_failure_detail(pull_proc)
            msg = 'partial pull: some vendors failed'
            if details:
                msg = f'{msg}: {details}'
            _log_sync(sync_type, 'all', 'error', 0, msg)

        load_proc = subprocess.run([sys.executable, load_path] + load_args, cwd=project_root, capture_output=True, text=True)
        if load_proc.stdout:
            logger.info('%s load stdout:\n%s', category, load_proc.stdout.strip())
        if load_proc.stderr:
            logger.warning('%s load stderr:\n%s', category, load_proc.stderr.strip())
        if load_proc.returncode == 0:
            done_msg = 'Manual category sync completed (partial pull)' if pull_partial else 'Manual category sync completed'
            _log_sync(sync_type, 'all', 'ok', 0, done_msg)
        else:
            details = _subprocess_failure_detail(load_proc)
            msg = f'load failed (code={load_proc.returncode})'
            if details:
                msg = f'{msg}: {details}'
            _log_sync(sync_type, 'all', 'error', 0, msg)
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
# Staged downloads (sync_downloads): delete after ingest — do not retain locally
# ---------------------------------------------------------------------------

def _try_unlink_sync_staging_paths(paths) -> None:
    """Remove files under ``LOCAL_DOWNLOAD_DIR`` after a successful pull+ingest."""
    from sync_config import LOCAL_DOWNLOAD_DIR

    try:
        root = os.path.normcase(os.path.normpath(os.path.abspath(LOCAL_DOWNLOAD_DIR)))
    except Exception:
        return
    for raw in paths:
        if not raw:
            continue
        try:
            ap = os.path.normcase(os.path.normpath(os.path.abspath(raw)))
            if not (ap == root or ap.startswith(root + os.sep)):
                logger.warning('Refusing to unlink outside sync_downloads: %s', ap)
                continue
            if os.path.isfile(ap):
                os.unlink(ap)
                logger.info('Removed staged sync file: %s', ap)
        except OSError as ex:
            logger.warning('Could not remove staged file %s: %s', raw, ex)


# ---------------------------------------------------------------------------
# Sync log helper
# ---------------------------------------------------------------------------

def _log_sync(sync_type, technology, status, rows=0, message=None):
    try:
        from db.runtime import connect_app, execute_query

        conn = connect_app()
        execute_query(
            conn,
            'INSERT INTO sync_log (sync_type, technology, status, rows_affected, message) VALUES (?,?,?,?,?)',
            (sync_type, technology, status, rows, message),
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
        NOKIA_PM_DB,
        PM_SYNC_FULL_CLEAR,
        PM_RETENTION_DAYS,
    )
    from .metadata_processor import seed_pm_cells_to_metadata

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
        _try_unlink_sync_staging_paths(list(downloaded.values()))
        _finish_progress('nokia_pm', True, 'Nokia PM sync completed.')
    except Exception as e:
        logger.exception('Nokia PM pull failed: %s', e)
        _log_sync('pm_nokia', 'all', 'error', 0, str(e))
        _finish_progress('nokia_pm', False, f'Nokia PM sync failed: {e}')


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
        HUAWEI_PM_DB,
        PM_RETENTION_DAYS,
    )
    from .metadata_processor import seed_pm_cells_to_metadata

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
        _try_unlink_sync_staging_paths([local_path])
        _finish_progress('huawei_pm', True, 'Huawei PM sync completed.')
    except Exception as e:
        logger.exception('Huawei PM pull failed: %s', e)
        _log_sync('pm_huawei', 'all', 'error', 0, str(e))
        _finish_progress('huawei_pm', False, f'Huawei PM sync failed: {e}')


# ---------------------------------------------------------------------------
# Metadata — root dir has dated snapshot folders; enter newest, pull 5 files
# ---------------------------------------------------------------------------

def pull_metadata():
    _finish_progress('metadata', True, 'Reset mode: Metadata pull disabled.')
    logger.info('Reset mode: pull_metadata is disabled.')
    return
    from sync_config import METADATA_SERVER, LOCAL_DOWNLOAD_DIR

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
        meta_paths = []
        for _k, v in downloaded.items():
            if isinstance(v, list):
                meta_paths.extend(p for p in v if p)
            elif v:
                meta_paths.append(v)
        _try_unlink_sync_staging_paths(meta_paths)
        _finish_progress('metadata', True, 'Metadata sync completed.')
    except Exception as e:
        logger.exception('Metadata pull failed: %s', e)
        _log_sync('metadata', 'all', 'error', 0, str(e))
        _finish_progress('metadata', False, f'Metadata sync failed: {e}')


# ---------------------------------------------------------------------------
# Groups (Nokia/Huawei)
# ---------------------------------------------------------------------------

def pull_nokia_groups():
    logger.info('Reset mode: pull_nokia_groups is disabled.')
    return
    from sync_config import NOKIA_GROUPS_SERVER, LOCAL_DOWNLOAD_DIR

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
        _try_unlink_sync_staging_paths([p for p in downloaded.values() if p])
    except Exception as e:
        logger.exception('Nokia Groups pull failed: %s', e)
        _log_sync('groups_nokia', 'all', 'error', 0, str(e))


def run_remote_pull_watcher_once():
    """
    One cycle of watcher orchestrator (--once): probe remotes,
    pull+load only when signatures change (state in databases/admin/pull_watch_state.json).
    """
    root = _PROJECT_ROOT
    script = os.path.join(root, 'pipeline', 'orchestrators', 'orchestrate_watcher_cycle.py')
    if not os.path.isfile(script):
        logger.warning('Remote pull watcher script not found: %s', script)
        return
    if not _pipeline_cycle_lock.acquire(blocking=False):
        logger.warning('Remote pull watcher skipped: another pipeline cycle is already running')
        return
    try:
        logger.info('Starting remote pull watcher orchestrator (--once)...')
        proc = subprocess.run(
            [sys.executable, script],
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
    finally:
        _pipeline_cycle_lock.release()


def pull_huawei_groups():
    logger.info('Reset mode: pull_huawei_groups is disabled.')
    return
    from sync_config import HUAWEI_GROUPS_SERVER, LOCAL_DOWNLOAD_DIR

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
        _try_unlink_sync_staging_paths([local_path])
    except Exception as e:
        logger.exception('Huawei Groups pull failed: %s', e)
        _log_sync('groups_huawei', 'all', 'error', 0, str(e))


# ---------------------------------------------------------------------------
# Network Health precalc (daily, after PM daily load)
# ---------------------------------------------------------------------------

def run_network_health_precalc(force: bool = False):
    """Build SQLite precalc tables for all vendor × RAT (daily KPI benchmarks)."""
    if os.environ.get('NH_DISABLE_PRECALC', '').strip().lower() in ('1', 'true', 'yes'):
        logger.info('Network Health precalc skipped (NH_DISABLE_PRECALC=1)')
        return
    try:
        from modules.network_health.precalc_job import build_all

        results = build_all(force=force)
        built = [r for r in results if not r.get('skipped') and not r.get('error')]
        skipped = [r for r in results if r.get('skipped')]
        errors = [r for r in results if r.get('error')]
        _log_sync(
            'network_health_precalc',
            'all',
            'ok' if not errors else 'error',
            sum(int(r.get('row_count') or 0) for r in built),
            f'built={len(built)} skipped={len(skipped)} errors={len(errors)}',
        )
        logger.info(
            'Network Health precalc finished: built=%s skipped=%s errors=%s',
            len(built),
            len(skipped),
            len(errors),
        )
    except Exception as e:
        _log_sync('network_health_precalc', 'all', 'error', 0, str(e))
        logger.exception('Network Health precalc failed: %s', e)


def refresh_nokia_cm_inventory():
    """Discover the Nokia NetAct NE inventory (CM Open API) and cache to disk."""
    try:
        from core.cm_extractor.config import nokia_configured, nokia_defaults
        from core.cm_extractor.nokia_client import NokiaCmClient
        from core.cm_extractor.nokia_discovery import refresh_nokia_inventory_cache

        if not nokia_configured():
            logger.info('Nokia CM inventory discovery skipped: Nokia CM not configured.')
            return

        cfg = nokia_defaults()
        client = NokiaCmClient(
            host=cfg['host'],
            username=cfg['username'],
            password=cfg['password'],
            base_url=cfg.get('base_url') or '',
            use_https=cfg['use_https'],
            verify_ssl=cfg['verify_ssl'],
            timeout=cfg.get('timeout', 180),
        )
        result = refresh_nokia_inventory_cache(client)
        counts = result.get('counts', {})
        errors = result.get('errors', {})
        total = sum(int(v or 0) for v in counts.values())
        status = 'ok' if (counts and not errors) else ('error' if errors and not counts else 'ok')
        msg = 'NetAct inventory: ' + ', '.join(f'{k}={v}' for k, v in counts.items())
        if errors:
            msg += ' | errors: ' + ', '.join(f'{k}: {v[:80]}' for k, v in errors.items())
        _log_sync('nokia_cm_inventory', 'all', status, total, msg)
        logger.info('Nokia CM inventory discovery finished: %s', msg)
    except Exception as e:
        _log_sync('nokia_cm_inventory', 'all', 'error', 0, str(e))
        logger.exception('Nokia CM inventory discovery failed: %s', e)


def run_cm_extractor_scheduled_jobs():
    """Dispatcher tick: execute any due CM Extractor scheduled jobs."""
    try:
        from core.cm_extractor.job_scheduler import run_due_jobs

        run_due_jobs()
    except Exception as e:
        logger.exception('CM extractor scheduled jobs tick failed: %s', e)


def run_cm_discrepancy_daily():
    """Daily full-network CM discrepancy audit (Nokia + Huawei)."""
    try:
        from core.cm_discrepancy.scheduler import run_cm_discrepancy_daily as run_daily

        # Nokia inventory should be fresh before resolving full-network targets.
        refresh_nokia_cm_inventory()
        results = run_daily()
        for vendor, result in (results or {}).items():
            if not isinstance(result, dict):
                continue
            if result.get('skipped'):
                _log_sync('cm_discrepancy', vendor, 'skipped', 0, result.get('reason'))
            elif result.get('error'):
                _log_sync('cm_discrepancy', vendor, 'error', 0, str(result.get('error'))[:350])
            else:
                _log_sync(
                    'cm_discrepancy',
                    vendor,
                    'ok' if result.get('status') == 'success' else 'error',
                    int(result.get('total_mismatches') or 0),
                    f"run #{result.get('run_id')}: {result.get('status')} "
                    f"({result.get('mo_count')} MO, {result.get('objects')} objects)",
                )
    except Exception as e:
        _log_sync('cm_discrepancy', 'all', 'error', 0, str(e))
        logger.exception('CM discrepancy daily audit failed: %s', e)


def _network_health_precalc_cron_hour() -> int:
    from modules.network_health import config as nh_cfg
    from sync_config import DAILY_PULL_HOUR

    hour = int(nh_cfg.PRECALC_CRON_HOUR)
    if hour < 0:
        return (int(DAILY_PULL_HOUR) + 1) % 24
    return max(0, min(23, hour))


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def _compute_scheduler_flags() -> dict:
    """Derive scheduler mode/flags from env + config.

    Used both when starting the scheduler and when reporting status from a
    process that does not itself host the scheduler (e.g. the web tier when the
    scheduler runs in a separate worker), so the dashboard reflects the
    configured intent instead of the ``unknown`` placeholder.
    """
    from sync_config import (
        RAW_PULL_INTERVAL_HOURS,
        DAILY_PULL_HOUR,
        PULL_WATCHER_POLL_INTERVAL_SEC,
    )

    legacy_enabled = os.environ.get('NCM_ENABLE_LEGACY_PERFORMANCE_SCHEDULER', '').strip().lower() in ('1', 'true', 'yes')
    watcher_disabled = os.environ.get('NCM_DISABLE_PULL_WATCHER', '').strip().lower() in ('1', 'true', 'yes')
    watcher_primary = os.environ.get('NCM_WATCHER_PRIMARY', '1').strip().lower() not in ('0', 'false', 'no')
    watcher_enabled = not watcher_disabled
    scheduled_ingest_enabled = (not watcher_enabled) or (not watcher_primary) or legacy_enabled

    if watcher_enabled and watcher_primary and not scheduled_ingest_enabled:
        mode = 'watcher-primary'
    elif watcher_enabled:
        mode = 'scheduled+verify'
    else:
        mode = 'scheduled-only'

    return {
        'mode': mode,
        'watcher_primary': bool(watcher_primary),
        'legacy_enabled': bool(legacy_enabled),
        'watcher_enabled': bool(watcher_enabled),
        'scheduled_ingest_enabled': bool(scheduled_ingest_enabled),
        'raw_pull_interval_hours': int(RAW_PULL_INTERVAL_HOURS),
        'daily_pull_hour': int(DAILY_PULL_HOUR),
        'watcher_poll_interval_sec': int(PULL_WATCHER_POLL_INTERVAL_SEC),
    }


def start_scheduler():
    global _scheduler
    global _scheduler_mode_summary

    from core.activation_gate import require_activation

    require_activation()

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
    flags = _compute_scheduler_flags()
    legacy_enabled = flags['legacy_enabled']
    watcher_enabled = flags['watcher_enabled']
    watcher_primary = flags['watcher_primary']
    scheduled_ingest_enabled = flags['scheduled_ingest_enabled']

    # Scheduled hourly + daily pull→load (OSS cadence: hourly every N hours, daily once per day).
    # In watcher-primary mode the watcher owns these SFTP pipelines, including daily scopes.
    if scheduled_ingest_enabled:
        _scheduler.add_job(
            run_full_sync_cycle,
            trigger=IntervalTrigger(hours=RAW_PULL_INTERVAL_HOURS),
            id='hourly_ingest_sync',
            name=f'Hourly SFTP pull + DB load (every {RAW_PULL_INTERVAL_HOURS}h)',
            replace_existing=True,
            next_run_time=datetime.now(),
            coalesce=True,
            max_instances=1,
        )
        _scheduler.add_job(
            run_daily_sync_cycle,
            trigger=CronTrigger(hour=DAILY_PULL_HOUR, minute=5),
            id='daily_ingest_sync',
            name=f'Daily SFTP pull + DB load ({DAILY_PULL_HOUR:02d}:05)',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    else:
        logger.info(
            'Hourly/daily SFTP ingest jobs not registered because remote watcher is primary.'
        )

    # Watcher: remote signature probe + DB ingest verification / retry.
    if watcher_enabled:
        _scheduler.add_job(
            run_remote_pull_watcher_once,
            trigger=IntervalTrigger(seconds=int(PULL_WATCHER_POLL_INTERVAL_SEC)),
            id='remote_pull_signature_watcher',
            name='Remote SFTP watcher (verify + gap fill)',
            replace_existing=True,
            next_run_time=datetime.now(),
            coalesce=True,
            max_instances=1,
        )

    precalc_disabled = os.environ.get('NH_DISABLE_PRECALC', '').strip().lower() in ('1', 'true', 'yes')
    if not precalc_disabled:
        from modules.network_health import config as nh_cfg

        _scheduler.add_job(
            run_network_health_precalc,
            trigger=CronTrigger(
                hour=_network_health_precalc_cron_hour(),
                minute=int(nh_cfg.PRECALC_CRON_MINUTE),
            ),
            id='network_health_precalc_daily',
            name='Network Health precalc (daily KPI tables)',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    # Nokia NetAct NE inventory: build preemptively at startup, refresh periodically.
    if os.environ.get('NCM_DISABLE_NOKIA_CM_INVENTORY', '').strip().lower() not in ('1', 'true', 'yes'):
        try:
            inv_hours = int(os.environ.get('NOKIA_CM_INVENTORY_REFRESH_HOURS', '6'))
        except ValueError:
            inv_hours = 6
        _scheduler.add_job(
            refresh_nokia_cm_inventory,
            trigger=IntervalTrigger(hours=max(1, inv_hours)),
            id='nokia_cm_inventory_discovery',
            name=f'Nokia NetAct NE inventory discovery (every {max(1, inv_hours)}h)',
            replace_existing=True,
            next_run_time=datetime.now(),
            coalesce=True,
            max_instances=1,
        )

    # CM Extractor scheduled jobs: poll every minute and run any that are due.
    if os.environ.get('NCM_DISABLE_CM_EXTRACTOR_SCHEDULER', '').strip().lower() not in ('1', 'true', 'yes'):
        _scheduler.add_job(
            run_cm_extractor_scheduled_jobs,
            trigger=IntervalTrigger(minutes=1),
            id='cm_extractor_scheduled_jobs',
            name='CM Extractor scheduled jobs dispatcher (every 1 min)',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    # CM Discrepancy Audit: daily full-network run (Nokia + Huawei), off-peak.
    try:
        from core.cm_discrepancy.scheduler import daily_hour as cm_discrepancy_daily_hour
        from core.cm_discrepancy.scheduler import enabled as cm_discrepancy_enabled

        if cm_discrepancy_enabled():
            disc_hour = cm_discrepancy_daily_hour()
            _scheduler.add_job(
                run_cm_discrepancy_daily,
                trigger=CronTrigger(hour=disc_hour, minute=0),
                id='cm_discrepancy_daily',
                name=f'CM Discrepancy Audit daily full-network run ({disc_hour:02d}:00)',
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
    except Exception:
        logger.exception('Failed to register CM discrepancy daily job')

    _scheduler.start()
    mode = flags['mode']
    _scheduler_mode_summary = dict(flags)
    logger.info(
        'Scheduler started — mode=%s scheduled_ingest=%s hourly_every=%sh daily_at=%02d:05 watcher=%s watcher_every=%ss legacy_master=%s',
        mode,
        scheduled_ingest_enabled,
        RAW_PULL_INTERVAL_HOURS,
        DAILY_PULL_HOUR,
        watcher_enabled,
        int(PULL_WATCHER_POLL_INTERVAL_SEC),
        legacy_enabled,
    )


def get_scheduler():
    return _scheduler


def get_scheduler_mode_summary() -> dict:
    # When this process hosts a running scheduler, report its live summary.
    if _scheduler is not None and _scheduler_mode_summary.get('mode') != 'unknown':
        return dict(_scheduler_mode_summary)
    # Otherwise (e.g. the web tier while the scheduler runs elsewhere), report
    # the configured intent from env/config rather than the 'unknown' default.
    try:
        summary = _compute_scheduler_flags()
        summary['scheduler_in_process'] = False
        return summary
    except Exception:
        return dict(_scheduler_mode_summary)

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
def trigger_nokia_cm_inventory_now(): refresh_nokia_cm_inventory()
def trigger_cm_extractor_jobs_now(): run_cm_extractor_scheduled_jobs()
def trigger_cm_discrepancy_now(): run_cm_discrepancy_daily()
