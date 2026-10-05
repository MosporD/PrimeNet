"""Enriched platform health for /healthz + stale-data event emit."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _debounce_path() -> str:
    try:
        from sync_config import DATA_ROOT

        root = DATA_ROOT
    except Exception:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "var", "data_stale_emit.json")


def _should_emit_stale(fingerprint: str) -> bool:
    debounce_min = max(1.0, _env_float("NCM_DATA_STALE_EMIT_DEBOUNCE_MIN", 30.0))
    path = _debounce_path()
    now = time.time()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                prev = json.load(fh)
            if (
                str(prev.get("fingerprint") or "") == fingerprint
                and now - float(prev.get("ts") or 0) < debounce_min * 60
            ):
                return False
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fingerprint": fingerprint, "ts": now}, fh)
    except Exception:
        pass
    return True


def collect_data_health(*, emit_stale: bool = True) -> dict[str, Any]:
    """PM + neighbor freshness snapshot; optionally emit platform.data_stale."""
    hourly_limit = _env_float("NCM_DATA_STALE_HOURS_HOURLY", 6.0)
    daily_limit = _env_float("NCM_DATA_STALE_HOURS_DAILY", 30.0)
    pm_payload: dict[str, Any] = {}
    neighbor_payload: dict[str, Any] = {}
    try:
        from core.pm_health import get_pm_health_cached

        pm_payload = get_pm_health_cached() or {}
    except Exception as exc:
        pm_payload = {"error": str(exc)}
    try:
        from core.neighbor_health import get_neighbor_health_cached

        neighbor_payload = get_neighbor_health_cached() or {}
    except Exception as exc:
        neighbor_payload = {"error": str(exc)}

    stale_items: list[dict[str, Any]] = []
    db_rows = list(pm_payload.get("pm_cell_databases") or []) + list(
        pm_payload.get("pm_group_databases") or []
    )
    for db in db_rows:
        if not isinstance(db, dict):
            continue
        label = str(db.get("label") or db.get("name") or "")
        is_daily = "daily" in label.lower()
        limit = daily_limit if is_daily else hourly_limit
        for table in db.get("stale_tables") or []:
            stale_items.append(
                {
                    "store": label,
                    "table": table,
                    "kind": "daily" if is_daily else "hourly",
                    "stale_after_hours": limit,
                }
            )
        if str(db.get("overall") or "").upper() == "STALE" and not db.get("stale_tables"):
            stale_items.append(
                {
                    "store": label,
                    "table": "*",
                    "kind": "daily" if is_daily else "hourly",
                    "stale_after_hours": limit,
                    "status": db.get("overall"),
                }
            )

    ok = not stale_items and "error" not in pm_payload
    # Compact summary for /healthz (avoid megabyte payloads)
    pm_summary = []
    for db in db_rows:
        if not isinstance(db, dict):
            continue
        pm_summary.append(
            {
                "label": db.get("label"),
                "overall": db.get("overall"),
                "latest_data_overall": db.get("latest_data_overall"),
                "stale_tables": db.get("stale_tables") or [],
                "row_count_total": db.get("row_count_total") or db.get("total_rows"),
            }
        )
    nb_summary = []
    for db in neighbor_payload.get("neighbor_databases") or []:
        if isinstance(db, dict):
            nb_summary.append(
                {
                    "label": db.get("label"),
                    "overall": db.get("overall") or db.get("status"),
                    "latest": db.get("latest_data_overall") or db.get("latest"),
                }
            )

    out = {
        "ok": ok,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "stale_hours": {"hourly": hourly_limit, "daily": daily_limit},
        "stale": stale_items,
        "pm": {
            "checked_at_utc": pm_payload.get("checked_at_utc"),
            "cached": pm_payload.get("cached"),
            "databases": pm_summary,
            "error": pm_payload.get("error"),
        },
        "neighbor": {
            "checked_at_utc": neighbor_payload.get("checked_at_utc"),
            "cached": neighbor_payload.get("cached"),
            "databases": nb_summary,
            "error": neighbor_payload.get("error"),
        },
    }

    if emit_stale and stale_items:
        fp = "|".join(
            sorted(f"{i.get('store')}:{i.get('table')}" for i in stale_items)
        )[:500]
        if _should_emit_stale(fp):
            try:
                from core.events import emit

                emit(
                    "platform.data_stale",
                    {
                        "stale_count": len(stale_items),
                        "stale": stale_items[:40],
                        "hourly_hours": hourly_limit,
                        "daily_hours": daily_limit,
                    },
                )
            except Exception as exc:
                logger.debug("stale emit skipped: %s", exc)
    return out


def build_healthz_payload(*, service: str = "primenet") -> tuple[dict[str, Any], int]:
    """Process readiness + data section. Returns (payload, http_status)."""
    try:
        from core.activation_gate import activation_status

        act = activation_status()
    except Exception as exc:
        return (
            {"status": "degraded", "service": service, "activation_error": str(exc)},
            503,
        )

    if not act.get("activated"):
        return (
            {
                "status": "locked",
                "service": service,
                "activation": act,
            },
            503,
        )

    payload: dict[str, Any] = {
        "status": "ok",
        "service": service,
        "activation": act,
    }
    try:
        from db.runtime import connect_app, execute_query

        conn = connect_app()
        try:
            execute_query(conn, "SELECT 1")
        finally:
            conn.close()
        payload["database"] = "ok"
    except Exception as exc:
        payload["status"] = "degraded"
        payload["database"] = str(exc)
        return payload, 503

    data = collect_data_health(emit_stale=True)
    payload["data"] = data
    if not data.get("ok"):
        payload["status"] = "degraded"
        # Process is up; data stale is degraded 200 so load balancers don't kill the app
        return payload, 200
    return payload, 200
