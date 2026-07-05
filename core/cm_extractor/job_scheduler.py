"""
CM Extractor scheduled jobs.

Users save a site + MO + parameter selection as a recurring job; a single
APScheduler "dispatcher" tick (see modules/sync/scheduler.py) calls
``run_due_jobs`` every minute to execute jobs whose ``next_run_at`` has passed.

Storage (app users DB):
  cm_extractor_jobs      — job definition + schedule + last status
  cm_extractor_job_runs  — one row per execution, with the produced file

Schedules are evaluated in server local time. ``next_run_at`` is stored as a
fixed-width ``YYYY-MM-DD HH:MM:SS`` string so lexical comparison equals time
comparison.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from db.runtime import connect_app, execute_query

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _REPO_ROOT / 'uploads' / 'cm_extractor' / 'scheduled_job'
_LEGACY_RESULTS_DIR = _REPO_ROOT / 'uploads' / 'cm_extractor' / 'scheduled'
_TS_FMT = '%Y-%m-%d %H:%M:%S'
_WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
_VALID_SCHEDULES = {'once', 'daily', 'weekly', 'interval'}
_DEFAULT_KEEP_RUNS = 5
_run_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _table_columns(conn, table: str) -> set[str]:
    cur = execute_query(conn, f'PRAGMA table_info({table})')
    return {str(row[1]) for row in cur.fetchall()}


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    if column not in _table_columns(conn, table):
        execute_query(conn, f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


def _migrate_job_schema(conn) -> None:
    _ensure_column(conn, 'cm_extractor_jobs', 'user_specific', 'INTEGER NOT NULL DEFAULT 1')
    _ensure_column(conn, 'cm_extractor_jobs', 'owner_username', 'TEXT')
    _ensure_column(conn, 'cm_extractor_jobs', 'storage_subpath', 'TEXT')
    execute_query(conn, '''
        UPDATE cm_extractor_jobs
        SET owner_username = (
            SELECT username FROM users WHERE users.id = cm_extractor_jobs.created_by
        )
        WHERE owner_username IS NULL OR TRIM(owner_username) = ''
    ''')


def ensure_tables() -> None:
    conn = connect_app()
    try:
        execute_query(conn, '''
            CREATE TABLE IF NOT EXISTS cm_extractor_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vendor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                schedule_time TEXT,
                schedule_days TEXT,
                interval_hours INTEGER,
                run_at TEXT,
                next_run_at TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                keep_runs INTEGER NOT NULL DEFAULT 5,
                user_specific INTEGER NOT NULL DEFAULT 1,
                owner_username TEXT,
                storage_subpath TEXT,
                last_run_at TEXT,
                last_status TEXT,
                last_message TEXT,
                created_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        execute_query(conn, '''
            CREATE TABLE IF NOT EXISTS cm_extractor_job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'running',
                trigger TEXT NOT NULL DEFAULT 'schedule',
                row_count INTEGER DEFAULT 0,
                message TEXT,
                file_name TEXT,
                file_path TEXT,
                created_by INTEGER,
                FOREIGN KEY (job_id) REFERENCES cm_extractor_jobs(id) ON DELETE CASCADE
            )
        ''')
        execute_query(conn, '''
            CREATE TABLE IF NOT EXISTS cm_extractor_job_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                job_name TEXT,
                run_id INTEGER,
                status TEXT NOT NULL,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                seen INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES cm_extractor_jobs(id) ON DELETE CASCADE
            )
        ''')
        _migrate_job_schema(conn)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schedule maths
# ---------------------------------------------------------------------------

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (_TS_FMT, '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_hhmm(value: str | None) -> tuple[int, int]:
    m = re.match(r'^\s*(\d{1,2}):(\d{2})\s*$', value or '')
    if not m:
        return 0, 0
    return max(0, min(23, int(m.group(1)))), max(0, min(59, int(m.group(2))))


def _parse_days(value: str | None) -> set[int]:
    out: set[int] = set()
    for tok in re.split(r'[,\s]+', (value or '').lower()):
        tok = tok.strip()[:3]
        if tok in _WEEKDAYS:
            out.add(_WEEKDAYS.index(tok))
    return out


def compute_next_run(job: dict[str, Any], base: datetime | None = None) -> str | None:
    """Next fire time as a ``_TS_FMT`` string, or None when the job will not fire again."""
    base = base or datetime.now()
    st = job.get('schedule_type')

    if st == 'once':
        dt = _parse_dt(job.get('run_at'))
        return dt.strftime(_TS_FMT) if dt and dt > base else None

    if st == 'interval':
        try:
            hours = max(1, int(job.get('interval_hours') or 1))
        except (TypeError, ValueError):
            hours = 1
        return (base + timedelta(hours=hours)).strftime(_TS_FMT)

    hh, mm = _parse_hhmm(job.get('schedule_time'))
    if st == 'daily':
        cand = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= base:
            cand += timedelta(days=1)
        return cand.strftime(_TS_FMT)

    if st == 'weekly':
        days = _parse_days(job.get('schedule_days')) or {base.weekday()}
        for add in range(0, 8):
            cand = (base + timedelta(days=add)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand > base and cand.weekday() in days:
                return cand.strftime(_TS_FMT)
        return None

    return None


def describe_schedule(job: dict[str, Any]) -> str:
    st = job.get('schedule_type')
    if st == 'once':
        return f"Once at {job.get('run_at') or '?'}"
    if st == 'interval':
        return f"Every {job.get('interval_hours') or 1}h"
    if st == 'daily':
        return f"Daily at {job.get('schedule_time') or '00:00'}"
    if st == 'weekly':
        days = job.get('schedule_days') or 'every day'
        return f"Weekly ({days}) at {job.get('schedule_time') or '00:00'}"
    return st or 'unknown'


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _row_to_job(row) -> dict[str, Any]:
    job = dict(row)
    try:
        job['payload'] = json.loads(job.get('payload_json') or '{}')
    except (TypeError, ValueError):
        job['payload'] = {}
    if not job.get('owner_username') and job.get('creator_username'):
        job['owner_username'] = job['creator_username']
    job['user_specific'] = bool(int(job.get('user_specific', 1) or 0))
    job['schedule_label'] = describe_schedule(job)
    job['storage_label'] = describe_storage_path(job)
    return job


def _username_slug(username: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', (username or 'unknown').strip())[:64] or 'unknown'


def normalize_storage_subpath(raw: str) -> str:
    """Safe relative folder under the owner username (e.g. ``lte/daily``)."""
    if not raw or not str(raw).strip():
        return ''
    parts: list[str] = []
    for seg in str(raw).replace('\\', '/').split('/'):
        seg = seg.strip()
        if not seg or seg in ('.', '..'):
            continue
        clean = re.sub(r'[^A-Za-z0-9._-]+', '_', seg)[:64]
        if clean:
            parts.append(clean)
    return '/'.join(parts)


def describe_storage_path(job: dict[str, Any]) -> str:
    username = _username_slug(job.get('owner_username') or 'unknown')
    sub = normalize_storage_subpath(job.get('storage_subpath') or '')
    if sub:
        return f'cm_extractor/scheduled_job/{username}/{sub}'
    return f'cm_extractor/scheduled_job/{username}'


def job_storage_dir(job: dict[str, Any]) -> Path:
    """Directory for one job's run files: ``…/scheduled_job/{user}/{subpath?}/{job_id}``."""
    username = _username_slug(job.get('owner_username') or 'unknown')
    sub = normalize_storage_subpath(job.get('storage_subpath') or '')
    path = _RESULTS_DIR / username
    if sub:
        path = path.joinpath(*sub.split('/'))
    return path / str(int(job['id']))


def create_job(*, name: str, vendor: str, payload: dict[str, Any], schedule_type: str,
               schedule_time: str = '', schedule_days: str = '', interval_hours: int | None = None,
               run_at: str = '', keep_runs: int = _DEFAULT_KEEP_RUNS, created_by: int,
               owner_username: str, user_specific: bool = True, storage_subpath: str = '') -> int:
    ensure_tables()
    vendor = (vendor or '').lower()
    schedule_type = (schedule_type or '').lower()
    if vendor not in ('nokia', 'huawei'):
        raise ValueError('vendor must be nokia or huawei')
    if schedule_type not in _VALID_SCHEDULES:
        raise ValueError(f'schedule_type must be one of {sorted(_VALID_SCHEDULES)}')
    if schedule_type in ('daily', 'weekly') and not re.match(r'^\d{1,2}:\d{2}$', schedule_time or ''):
        raise ValueError('A time (HH:MM) is required for daily/weekly schedules')
    if schedule_type == 'weekly' and not _parse_days(schedule_days):
        raise ValueError('Select at least one weekday for a weekly schedule')
    if schedule_type == 'interval' and not (interval_hours and int(interval_hours) >= 1):
        raise ValueError('interval_hours must be >= 1')
    if schedule_type == 'once':
        dt = _parse_dt(run_at)
        if not dt or dt <= datetime.now():
            raise ValueError('A future date/time is required for a one-time job')

    job_stub = {
        'schedule_type': schedule_type,
        'schedule_time': schedule_time,
        'schedule_days': schedule_days,
        'interval_hours': interval_hours,
        'run_at': run_at,
    }
    next_run = compute_next_run(job_stub)
    owner = (owner_username or '').strip() or 'unknown'
    subpath = normalize_storage_subpath(storage_subpath)

    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            INSERT INTO cm_extractor_jobs (
                name, vendor, payload_json, schedule_type, schedule_time, schedule_days,
                interval_hours, run_at, next_run_at, enabled, keep_runs,
                user_specific, owner_username, storage_subpath, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        ''', (
            name.strip() or f'{vendor} extraction',
            vendor,
            json.dumps(payload),
            schedule_type,
            schedule_time or None,
            schedule_days or None,
            int(interval_hours) if interval_hours else None,
            run_at or None,
            next_run,
            max(1, int(keep_runs or _DEFAULT_KEEP_RUNS)),
            1 if user_specific else 0,
            owner,
            subpath or None,
            int(created_by),
        ))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_jobs(*, user_id: int | None = None, include_all: bool = False) -> list[dict[str, Any]]:
    ensure_tables()
    conn = connect_app()
    try:
        if include_all:
            cur = execute_query(conn, '''
                SELECT j.*, u.username AS creator_username
                FROM cm_extractor_jobs j LEFT JOIN users u ON j.created_by = u.id
                ORDER BY j.created_at DESC
            ''')
        else:
            cur = execute_query(conn, '''
                SELECT j.*, u.username AS creator_username
                FROM cm_extractor_jobs j LEFT JOIN users u ON j.created_by = u.id
                WHERE j.created_by = ?
                ORDER BY j.created_at DESC
            ''', (int(user_id or 0),))
        return [_row_to_job(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_job(job_id: int) -> dict[str, Any] | None:
    ensure_tables()
    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            SELECT j.*, u.username AS creator_username
            FROM cm_extractor_jobs j
            LEFT JOIN users u ON j.created_by = u.id
            WHERE j.id = ?
        ''', (int(job_id),))
        row = cur.fetchone()
        return _row_to_job(row) if row else None
    finally:
        conn.close()


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    try:
        stop = stop_at.resolve()
        cur = path.resolve()
        while cur != stop and cur.is_dir() and not any(cur.iterdir()):
            cur.rmdir()
            cur = cur.parent
    except OSError:
        pass


def delete_job(job_id: int) -> None:
    ensure_tables()
    job = get_job(job_id)
    runs = list_runs(job_id)
    for run in runs:
        _safe_unlink(run.get('file_path'))
    job_dir = job_storage_dir(job) if job else _LEGACY_RESULTS_DIR / str(job_id)
    conn = connect_app()
    try:
        execute_query(conn, 'DELETE FROM cm_extractor_job_runs WHERE job_id = ?', (int(job_id),))
        execute_query(conn, 'DELETE FROM cm_extractor_jobs WHERE id = ?', (int(job_id),))
        conn.commit()
    finally:
        conn.close()
    if job_dir.is_dir():
        _prune_empty_parents(job_dir, _RESULTS_DIR)
    legacy_dir = _LEGACY_RESULTS_DIR / str(job_id)
    if legacy_dir.is_dir():
        _prune_empty_parents(legacy_dir, _LEGACY_RESULTS_DIR)


def set_enabled(job_id: int, enabled: bool) -> None:
    ensure_tables()
    conn = connect_app()
    try:
        if enabled:
            cur = execute_query(conn, 'SELECT * FROM cm_extractor_jobs WHERE id = ?', (int(job_id),))
            row = cur.fetchone()
            if not row:
                return
            next_run = compute_next_run(dict(row))
            execute_query(conn, '''
                UPDATE cm_extractor_jobs SET enabled = 1, next_run_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (next_run, int(job_id)))
        else:
            execute_query(conn, '''
                UPDATE cm_extractor_jobs SET enabled = 0, next_run_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (int(job_id),))
        conn.commit()
    finally:
        conn.close()


def list_runs(job_id: int, limit: int = 50) -> list[dict[str, Any]]:
    ensure_tables()
    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            SELECT r.*, u.username AS run_by_username
            FROM cm_extractor_job_runs r
            LEFT JOIN users u ON r.created_by = u.id
            WHERE r.job_id = ?
            ORDER BY r.id DESC LIMIT ?
        ''', (int(job_id), int(limit)))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_run(run_id: int) -> dict[str, Any] | None:
    ensure_tables()
    conn = connect_app()
    try:
        cur = execute_query(conn, 'SELECT * FROM cm_extractor_job_runs WHERE id = ?', (int(run_id),))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def _slug(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', (value or 'job').strip())[:50] or 'job'


def _apply_retention(job_id: int, keep_runs: int) -> None:
    keep = max(1, int(keep_runs or _DEFAULT_KEEP_RUNS))
    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            SELECT id, file_path FROM cm_extractor_job_runs WHERE job_id = ?
            ORDER BY id DESC
        ''', (int(job_id),))
        rows = [dict(r) for r in cur.fetchall()]
        for stale in rows[keep:]:
            _safe_unlink(stale.get('file_path'))
            execute_query(conn, 'DELETE FROM cm_extractor_job_runs WHERE id = ?', (stale['id'],))
        conn.commit()
    finally:
        conn.close()


def run_job(job_id: int, *, trigger: str = 'schedule', actor_id: int | None = None,
            advance_schedule: bool = True) -> dict[str, Any]:
    """Execute one job: produce the workbook, record the run, apply retention."""
    job = get_job(job_id)
    if not job:
        return {'success': False, 'error': 'Job not found'}

    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            INSERT INTO cm_extractor_job_runs (job_id, status, trigger, created_by)
            VALUES (?, 'running', ?, ?)
        ''', (int(job_id), trigger, int(actor_id or job['created_by'])))
        run_id = int(cur.lastrowid)
        execute_query(conn, '''
            UPDATE cm_extractor_jobs SET last_status = 'running', last_run_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (datetime.now().strftime(_TS_FMT), int(job_id)))
        conn.commit()
    finally:
        conn.close()

    job_dir = job_storage_dir(job)
    job_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f"{job['vendor']}_{_slug(job['name'])}_{ts}.xlsx"
    out_path = job_dir / f'{run_id}_{file_name}'

    status, message, row_count, saved_path = 'error', '', 0, None
    try:
        from core.cm_extractor.extraction import run_extraction

        result = run_extraction(job['payload'], str(out_path))
        row_count = int(result.get('row_count') or 0)
        message = result.get('summary') or f'{row_count} row(s).'
        status, saved_path = 'ok', str(out_path)
    except Exception as exc:  # surface any extraction error into the run history
        status, message = 'error', str(exc)
        _safe_unlink(str(out_path))
        logger.exception('CM scheduled job %s failed: %s', job_id, exc)

    conn = connect_app()
    try:
        execute_query(conn, '''
            UPDATE cm_extractor_job_runs
            SET status = ?, finished_at = CURRENT_TIMESTAMP, row_count = ?, message = ?,
                file_name = ?, file_path = ?
            WHERE id = ?
        ''', (status, row_count, message[:1000], file_name if saved_path else None, saved_path, run_id))

        next_run = job.get('next_run_at')
        if advance_schedule:
            next_run = None if job['schedule_type'] == 'once' else compute_next_run(job)
        execute_query(conn, '''
            UPDATE cm_extractor_jobs
            SET last_status = ?, last_message = ?, last_run_at = ?, next_run_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, message[:1000], datetime.now().strftime(_TS_FMT), next_run, int(job_id)))
        conn.commit()
    finally:
        conn.close()

    _apply_retention(job_id, job.get('keep_runs') or _DEFAULT_KEEP_RUNS)
    emit_job_notification(job, run_id, status, message, trigger=trigger)
    return {'success': status == 'ok', 'run_id': run_id, 'status': status, 'message': message}


def run_due_jobs() -> int:
    """Dispatcher tick: run every enabled job whose next_run_at has passed."""
    ensure_tables()
    if not _run_lock.acquire(blocking=False):
        logger.info('CM scheduler tick skipped: previous tick still running.')
        return 0
    try:
        now = datetime.now().strftime(_TS_FMT)
        conn = connect_app()
        try:
            cur = execute_query(conn, '''
                SELECT id FROM cm_extractor_jobs
                WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at ASC
            ''', (now,))
            due_ids = [int(r['id']) for r in cur.fetchall()]
        finally:
            conn.close()

        for job_id in due_ids:
            try:
                run_job(job_id, trigger='schedule')
            except Exception as exc:
                logger.exception('CM scheduled job %s dispatch failed: %s', job_id, exc)
        if due_ids:
            logger.info('CM scheduler ran %d due job(s).', len(due_ids))
        return len(due_ids)
    finally:
        _run_lock.release()


# ---------------------------------------------------------------------------
# Notifications (scheduled runs → in-app toasts)
# ---------------------------------------------------------------------------

def emit_job_notification(
    job: dict[str, Any],
    run_id: int,
    status: str,
    message: str,
    *,
    trigger: str = 'schedule',
) -> None:
    """Record an in-app notification when an unattended scheduled job finishes."""
    if trigger != 'schedule':
        return
    ensure_tables()
    user_id = int(job.get('created_by') or 0)
    if not user_id:
        return
    conn = connect_app()
    try:
        execute_query(conn, '''
            INSERT INTO cm_extractor_job_notifications (
                user_id, job_id, job_name, run_id, status, message
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            int(job['id']),
            str(job.get('name') or 'CM extraction')[:200],
            int(run_id),
            str(status or 'error')[:32],
            str(message or '')[:1000],
        ))
        conn.commit()
    finally:
        conn.close()


def list_job_notifications(
    *,
    user_id: int,
    since_id: int = 0,
    unread_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_tables()
    conn = connect_app()
    try:
        sql = '''
            SELECT id, user_id, job_id, job_name, run_id, status, message, created_at, seen
            FROM cm_extractor_job_notifications
            WHERE user_id = ? AND id > ?
        '''
        params: list[Any] = [int(user_id), int(since_id)]
        if unread_only:
            sql += ' AND seen = 0'
        sql += ' ORDER BY id ASC LIMIT ?'
        params.append(max(1, min(int(limit), 100)))
        cur = execute_query(conn, sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            row['seen'] = bool(int(row.get('seen') or 0))
        return rows
    finally:
        conn.close()


def count_unread_notifications(user_id: int) -> int:
    ensure_tables()
    conn = connect_app()
    try:
        cur = execute_query(conn, '''
            SELECT COUNT(*) AS c FROM cm_extractor_job_notifications
            WHERE user_id = ? AND seen = 0
        ''', (int(user_id),))
        row = cur.fetchone()
        return int(row['c'] if row else 0)
    finally:
        conn.close()


def mark_notifications_seen(*, user_id: int, ids: list[int] | None = None) -> int:
    ensure_tables()
    conn = connect_app()
    try:
        if ids:
            clean = [int(i) for i in ids if int(i) > 0]
            if not clean:
                return 0
            placeholders = ','.join('?' * len(clean))
            cur = execute_query(conn, f'''
                UPDATE cm_extractor_job_notifications
                SET seen = 1
                WHERE user_id = ? AND id IN ({placeholders})
            ''', (int(user_id), *clean))
        else:
            cur = execute_query(conn, '''
                UPDATE cm_extractor_job_notifications SET seen = 1 WHERE user_id = ?
            ''', (int(user_id),))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()
