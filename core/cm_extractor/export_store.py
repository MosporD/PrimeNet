"""Persist CM Extractor export workbooks on disk for later download."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sync_config import PROJECT_ROOT

_EXPORTS_ROOT = Path(PROJECT_ROOT) / 'uploads' / 'cm_extractor' / 'exports'
_LOCK = threading.RLock()
_TTL_SEC = int(os.environ.get('CM_EXPORT_RETENTION_SEC', str(7 * 24 * 3600)))
_MAX_PER_USER = int(os.environ.get('CM_EXPORT_MAX_PER_USER', '50'))


def _safe_user_id(user_id: str | int | None) -> str:
    token = str(user_id or 'unknown').strip() or 'unknown'
    return re.sub(r'[^\w.\-]+', '_', token)[:64]


def _meta_path(file_id: str) -> Path:
    return _EXPORTS_ROOT / f'{file_id}.json'


def _purge_expired_locked(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    if not _EXPORTS_ROOT.is_dir():
        return
    for meta_file in _EXPORTS_ROOT.glob('*.json'):
        try:
            record = json.loads(meta_file.read_text(encoding='utf-8'))
            stored_at = float(record.get('stored_at') or meta_file.stat().st_mtime)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            stored_at = meta_file.stat().st_mtime if meta_file.exists() else 0
        if ts - stored_at > _TTL_SEC:
            file_id = meta_file.stem
            delete_export(file_id)


def _trim_user_exports_locked(user_id: str) -> None:
    prefix = f'"user_id": "{user_id}"'
    metas: list[tuple[float, Path]] = []
    for meta_file in _EXPORTS_ROOT.glob('*.json'):
        try:
            text = meta_file.read_text(encoding='utf-8')
            if prefix not in text:
                continue
            record = json.loads(text)
            metas.append((float(record.get('stored_at') or 0), meta_file))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    metas.sort(key=lambda item: item[0])
    while len(metas) > _MAX_PER_USER:
        _, meta_file = metas.pop(0)
        delete_export(meta_file.stem)


def create_export_path(
    *,
    user_id: str | int | None,
    filename: str,
    vendor: str = '',
    label: str = '',
) -> tuple[str, Path]:
    """Reserve a new export id and destination path on disk."""
    file_id = str(uuid.uuid4())
    safe_name = re.sub(r'[^\w.\-]+', '_', (filename or 'cm_extract.xlsx').strip()) or 'cm_extract.xlsx'
    if not safe_name.lower().endswith('.xlsx'):
        safe_name += '.xlsx'
    now = time.time()
    with _LOCK:
        _EXPORTS_ROOT.mkdir(parents=True, exist_ok=True)
        _purge_expired_locked(now)
        user_key = _safe_user_id(user_id)
        _trim_user_exports_locked(user_key)
        dest = _EXPORTS_ROOT / f'{file_id}_{safe_name}'
        record = {
            'file_id': file_id,
            'path': str(dest),
            'filename': safe_name,
            'user_id': user_key,
            'vendor': vendor,
            'label': label,
            'stored_at': now,
            'status': 'pending',
        }
        _meta_path(file_id).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return file_id, dest


def update_export_record(file_id: str, **fields: Any) -> None:
    with _LOCK:
        record = get_export_record(file_id, check_user=False) or {}
        if not record:
            return
        record.update(fields)
        _meta_path(file_id).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')


def get_export_record(
    file_id: str,
    *,
    user_id: str | int | None = None,
    check_user: bool = True,
    require_file: bool = True,
) -> dict[str, Any] | None:
    token = str(file_id or '').strip()
    if not token:
        return None
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        meta = _meta_path(token)
        if not meta.is_file():
            return None
        try:
            record = json.loads(meta.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        stored_at = float(record.get('stored_at') or meta.stat().st_mtime)
        if now - stored_at > _TTL_SEC:
            delete_export(token)
            return None
    if check_user:
        owner = str(record.get('user_id') or '')
        caller = _safe_user_id(user_id)
        if owner and caller and owner != caller:
            return None
    status = str(record.get('status') or 'done')
    path = Path(str(record.get('path') or ''))
    if require_file and status == 'done' and not path.is_file():
        return None
    return record


def delete_export(file_id: str) -> None:
    token = str(file_id or '').strip()
    if not token:
        return
    with _LOCK:
        meta = _meta_path(token)
        record: dict[str, Any] = {}
        if meta.is_file():
            try:
                record = json.loads(meta.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                record = {}
            meta.unlink(missing_ok=True)
        path = Path(str(record.get('path') or ''))
        if path.is_file():
            path.unlink(missing_ok=True)


def list_user_exports(user_id: str | int | None, *, limit: int = 20) -> list[dict[str, Any]]:
    user_key = _safe_user_id(user_id)
    now = time.time()
    items: list[dict[str, Any]] = []
    with _LOCK:
        _purge_expired_locked(now)
        for meta in _EXPORTS_ROOT.glob('*.json'):
            try:
                record = json.loads(meta.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            if str(record.get('user_id') or '') != user_key:
                continue
            if str(record.get('status') or 'done') != 'done':
                continue
            path = Path(str(record.get('path') or ''))
            if not path.is_file():
                continue
            items.append({
                'file_id': record.get('file_id') or meta.stem,
                'filename': record.get('filename') or path.name,
                'vendor': record.get('vendor') or '',
                'label': record.get('label') or '',
                'row_count': record.get('row_count'),
                'stored_at': record.get('stored_at'),
                'summary': record.get('summary') or '',
            })
    items.sort(key=lambda row: float(row.get('stored_at') or 0), reverse=True)
    return items[: max(1, limit)]
