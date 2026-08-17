"""Best-effort live FM fetch joined to cell/site names. Never blocks the UI long."""

from __future__ import annotations

import threading
import time
from typing import Any

_CACHE_TTL = 300
_lock = threading.Lock()
_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def _tokens(text: str) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    parts = []
    for chunk in raw.replace("/", " ").replace("_", " ").replace("-", " ").split():
        if len(chunk) >= 3:
            parts.append(chunk)
    if raw:
        parts.append(raw)
    return parts


def _try_huawei_alarms(limit: int) -> tuple[list[dict], str | None]:
    from core.cm_extractor.config import huawei_configured
    from core.cm_extractor.extraction import build_huawei_client
    from core.cm_extractor.huawei_discovery import fetch_fm_alarms

    if not huawei_configured():
        return [], "huawei_fm_not_configured"
    try:
        client = build_huawei_client()
        client.timeout = min(int(getattr(client, "timeout", 30) or 30), 12)
        result = fetch_fm_alarms(client, data_type="CURRENT", limit=limit)
        return list(result.get("alarms") or []), None
    except Exception as exc:
        return [], f"huawei_fm_error:{exc}"


def _try_nokia_alarms(limit: int) -> tuple[list[dict], str | None]:
    from core.cm_extractor.config import nokia_fm_configured, nokia_fm_missing_settings

    if not nokia_fm_configured():
        missing = nokia_fm_missing_settings()
        return [], "nokia_fm_not_configured" + (f":{','.join(missing)}" if missing else "")
    try:
        from modules.fault_management.routes import _fetch_netact_fm_alarms

        result = _fetch_netact_fm_alarms({"limit": limit, "period_hours": 6})
        return list(result.get("alarms") or []), None
    except Exception as exc:
        return [], f"nokia_fm_error:{exc}"


def fetch_recent_alarms(*, limit: int = 200, force: bool = False) -> dict[str, Any]:
    now = time.time()
    with _lock:
        if not force and _cache.get("payload") and now < float(_cache.get("expires_at") or 0):
            out = dict(_cache["payload"])
            out["cached"] = True
            return out

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    alarms: list[dict] = []
    notes: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        hw_fut = pool.submit(_try_huawei_alarms, limit)
        nok_fut = pool.submit(_try_nokia_alarms, limit)
        try:
            hw, hw_note = hw_fut.result(timeout=8)
        except FuturesTimeout:
            hw, hw_note = [], "huawei_fm_timeout"
        if hw_note:
            notes.append(hw_note)
        alarms.extend(hw)
        try:
            nok, nok_note = nok_fut.result(timeout=8)
        except FuturesTimeout:
            nok, nok_note = [], "nokia_fm_timeout"
        if nok_note:
            notes.append(nok_note)
        alarms.extend(nok)

    payload = {
        "alarms": alarms,
        "count": len(alarms),
        "notes": notes,
        "configured": any("not_configured" not in n for n in notes) or bool(alarms),
        "cached": False,
    }
    with _lock:
        _cache["payload"] = payload
        _cache["expires_at"] = now + _CACHE_TTL
    return payload


def match_alarms_for_cells(cell_names: list[str], site_ids: list[str] | None = None) -> dict[str, list[dict]]:
    payload = fetch_recent_alarms()
    alarms = payload.get("alarms") or []
    if not alarms:
        return {}
    needles: list[tuple[str, list[str]]] = []
    for cell in cell_names:
        key = str(cell or "").strip()
        if key:
            needles.append((key.lower(), _tokens(key)))
    for site in site_ids or []:
        key = str(site or "").strip()
        if key:
            needles.append((key.lower(), _tokens(key)))

    hits: dict[str, list[dict]] = {}
    for alarm in alarms:
        blob = " ".join(
            str(alarm.get(k) or "")
            for k in ("me_name", "site_id", "location_info", "alarm_name", "probable_cause")
        ).lower()
        for key, tokens in needles:
            if key and key in blob:
                hits.setdefault(key, []).append(alarm)
                continue
            if tokens and any(tok in blob for tok in tokens if len(tok) >= 4):
                hits.setdefault(key, []).append(alarm)
    return hits
