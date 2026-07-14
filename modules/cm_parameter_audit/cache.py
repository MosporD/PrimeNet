"""Disk-backed short-lived cache for CM Parameter Audit export payloads.

In-memory-only storage breaks under Gunicorn: the live scan and export request
can land on different workers, so the export_id is missing on export.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sync_config import PROJECT_ROOT

_CACHE_DIR = Path(PROJECT_ROOT) / 'uploads' / 'cm_parameter_audit' / 'exports'
_LOCK = threading.Lock()
_TTL_SEC = 3600
_MAX_ENTRIES = 48


def _safe_export_id(export_id: str) -> str | None:
    token = str(export_id or '').strip()
    if not token:
        return None
    try:
        uuid.UUID(token)
    except ValueError:
        return None
    return token


def _cache_path(export_id: str) -> Path:
    return _CACHE_DIR / f'{export_id}.json'


def _purge_expired_locked(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    if not _CACHE_DIR.is_dir():
        return
    for path in _CACHE_DIR.glob('*.json'):
        try:
            stored_at = path.stat().st_mtime
        except OSError:
            continue
        if ts - stored_at > _TTL_SEC:
            path.unlink(missing_ok=True)


def _trim_oldest_locked() -> None:
    if not _CACHE_DIR.is_dir():
        return
    files = sorted(
        _CACHE_DIR.glob('*.json'),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
    )
    while len(files) >= _MAX_ENTRIES:
        oldest = files.pop(0)
        oldest.unlink(missing_ok=True)


def store_export_payload(payload: dict[str, Any], *, user_id: str | int | None = None) -> str:
    export_id = str(uuid.uuid4())
    now = time.time()
    record = {
        'user_id': str(user_id) if user_id not in (None, '') else '',
        'stored_at': now,
        'payload': payload,
    }
    with _LOCK:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _purge_expired_locked(now)
        _trim_oldest_locked()
        _cache_path(export_id).write_text(
            json.dumps(record, ensure_ascii=False, default=str),
            encoding='utf-8',
        )
    return export_id


def get_export_payload(export_id: str, *, user_id: str | int | None = None) -> dict[str, Any] | None:
    token = _safe_export_id(export_id)
    if not token:
        return None
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        path = _cache_path(token)
        if not path.is_file():
            return None
        try:
            stored_at = path.stat().st_mtime
            if now - stored_at > _TTL_SEC:
                path.unlink(missing_ok=True)
                return None
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            return None

    owner = str(record.get('user_id') or '')
    caller = str(user_id) if user_id not in (None, '') else ''
    if owner and caller and owner != caller:
        return None
    payload = record.get('payload')
    return dict(payload) if isinstance(payload, dict) else None
