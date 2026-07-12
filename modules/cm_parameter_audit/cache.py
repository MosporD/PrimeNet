"""Short-lived server cache for CM Parameter Audit export payloads."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_CACHE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_TTL_SEC = 3600
_MAX_ENTRIES = 24


def _purge_expired_locked(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    expired = [key for key, item in _CACHE.items() if ts - float(item.get('stored_at') or 0) > _TTL_SEC]
    for key in expired:
        _CACHE.pop(key, None)


def store_export_payload(payload: dict[str, Any], *, user_id: str | int | None = None) -> str:
    export_id = str(uuid.uuid4())
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        if len(_CACHE) >= _MAX_ENTRIES:
            oldest_key = min(_CACHE.items(), key=lambda item: float(item[1].get('stored_at') or 0))[0]
            _CACHE.pop(oldest_key, None)
        _CACHE[export_id] = {
            'payload': payload,
            'stored_at': now,
            'user_id': str(user_id) if user_id not in (None, '') else '',
        }
    return export_id


def get_export_payload(export_id: str, *, user_id: str | int | None = None) -> dict[str, Any] | None:
    token = str(export_id or '').strip()
    if not token:
        return None
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        item = _CACHE.get(token)
        if not item:
            return None
        owner = str(item.get('user_id') or '')
        caller = str(user_id) if user_id not in (None, '') else ''
        if owner and caller and owner != caller:
            return None
        payload = item.get('payload')
        return dict(payload) if isinstance(payload, dict) else None
