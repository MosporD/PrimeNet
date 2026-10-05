"""Dashboard My Day personalization payload.

Honest empties only — never invent KPI movers or case counts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Prefer these when suggesting pins for RF-ish roles.
_ROLE_PIN_SUGGESTIONS = {
    "default": [
        {"module_id": "sector-health", "name": "Sector Health", "href": "/sector-health"},
        {"module_id": "sleeping-cells", "name": "Sleeping Cells", "href": "/sleeping-cells"},
        {"module_id": "optimization-cases", "name": "Optimization Cases", "href": "/optimization-cases"},
    ],
}

_ACTION_TO_TOOL = {
    "performance_view": {"name": "Performance Explorer", "href": "/performance"},
    "map_view": {"name": "Network Topology", "href": "/network-map"},
    "heatmap_view": {"name": "Network Coverage Heatmap", "href": "/cell-heatmap"},
    "optimization_case_create": {"name": "Optimization Cases", "href": "/optimization-cases"},
    "optimization_case_from_issue": {"name": "Optimization Cases", "href": "/optimization-cases"},
    "mo_browse": {"name": "Parameter Dictionary", "href": "/parameter-dictionary"},
    "mo_search": {"name": "Parameter Dictionary", "href": "/parameter-dictionary"},
    "adjacency_gis_refresh": {"name": "Adjacency GIS", "href": "/adjacency-gis"},
    "export": {"name": "Network Topology", "href": "/network-map"},
}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_prefs(user_id: int) -> dict:
    try:
        from db.runtime import execute_query
        from database_enhanced import get_db

        conn = get_db()
        row = execute_query(
            conn,
            "SELECT preferences FROM user_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return {}
        raw = row["preferences"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        prefs = json.loads(raw or "{}")
        return prefs if isinstance(prefs, dict) else {}
    except Exception:
        logger.exception("my-day: failed loading preferences")
        return {}


def _save_prefs_merge(user_id: int, patch: dict) -> None:
    if not user_id:
        return
    try:
        from db.runtime import execute_query
        from database_enhanced import get_db

        conn = get_db()
        row = execute_query(
            conn,
            "SELECT preferences FROM user_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        merged: dict = {}
        if row:
            raw = row["preferences"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            try:
                parsed = json.loads(raw or "{}")
                if isinstance(parsed, dict):
                    merged = parsed
            except (TypeError, json.JSONDecodeError):
                merged = {}
        merged.update(patch)
        prefs_json = json.dumps(merged)
        execute_query(
            conn,
            """
            INSERT INTO user_preferences (user_id, preferences)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET preferences = excluded.preferences, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, prefs_json),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("my-day: failed saving preferences")


def _needs_you(username: str) -> dict:
    empty = {
        "assigned": 0,
        "awaiting_verification": 0,
        "approvals_pending": 0,
        "total": 0,
        "href": "/optimization-cases",
        "empty": True,
        "message": "Nothing assigned to you right now.",
    }
    if not username:
        return empty
    try:
        from core.cases import store as cases_store

        assigned = cases_store.list_cases(state="assigned", owner=username, limit=50)
        verifying = cases_store.list_cases(state="verifying", owner=username, limit=50)
        proposed = cases_store.list_cases(state="proposed", owner=username, limit=50)
        a, v, p = len(assigned), len(verifying), len(proposed)
        total = a + v + p
        if total == 0:
            return empty
        return {
            "assigned": a,
            "awaiting_verification": v,
            "approvals_pending": p,
            "total": total,
            "href": "/optimization-cases",
            "empty": False,
            "message": "",
        }
    except Exception:
        logger.exception("my-day: needs_you failed")
        return empty


def _since_last_visit(username: str, user_id: int, since: datetime | None) -> dict:
    away_hours = None
    now = datetime.now(timezone.utc)
    if since is not None:
        away_hours = max(0, int((now - since).total_seconds() // 3600))

    items: list[dict] = []
    if since is not None and username:
        try:
            from core.cases import store as cases_store

            closed = cases_store.list_cases(state="closed", owner=username, limit=50)
            closed_since = 0
            for case in closed:
                updated = _parse_ts(case.get("updated_at"))
                if updated and updated >= since:
                    closed_since += 1
            if closed_since:
                items.append(
                    {
                        "text": f"{closed_since} case{'s' if closed_since != 1 else ''} closed on your watch",
                        "href": "/optimization-cases",
                    }
                )
        except Exception:
            logger.exception("my-day: since_last_visit cases failed")

        try:
            from database_enhanced import get_db
            from db.runtime import execute_query

            conn = get_db()
            rows = execute_query(
                conn,
                """
                SELECT action, details, timestamp
                FROM activity_log
                WHERE user_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 20
                """,
                (user_id, since.replace(tzinfo=None) if since.tzinfo else since),
            ).fetchall()
            conn.close()
            interesting = 0
            for row in rows:
                action = row["action"] if hasattr(row, "keys") else row[0]
                if action in _ACTION_TO_TOOL or str(action).startswith("optimization_case"):
                    interesting += 1
            if interesting and not any("case" in (i.get("text") or "").lower() for i in items):
                items.append(
                    {
                        "text": f"{interesting} tool action{'s' if interesting != 1 else ''} since last visit",
                        "href": None,
                    }
                )
        except Exception:
            logger.exception("my-day: since_last_visit activity failed")

    if not items:
        return {
            "away_hours": away_hours,
            "empty": True,
            "message": "No network changes logged since your last visit.",
            "items": [],
        }
    return {
        "away_hours": away_hours,
        "empty": False,
        "message": "",
        "items": items[:4],
    }


def _watchlist(prefs: dict) -> dict:
    raw = prefs.get("my_day_watchlist")
    if not isinstance(raw, dict) or not (raw.get("label") or raw.get("id")):
        return {
            "configured": False,
            "empty": True,
            "message": "Set a cluster, region, or site list to watch.",
            "label": None,
            "href": "/network-health",
            "movers": [],
        }
    label = str(raw.get("label") or raw.get("id") or "").strip()
    href = str(raw.get("href") or "/network-health").strip() or "/network-health"
    # KPI movers are not wired yet — show configured watchlist without invented numbers.
    return {
        "configured": True,
        "empty": False,
        "message": "KPI movers for this watchlist are not connected yet.",
        "label": label,
        "scope": str(raw.get("type") or raw.get("scope") or "watchlist"),
        "href": href,
        "movers": [],
    }


def _continue_tools(user_id: int) -> dict:
    items: list[dict] = []
    seen: set[str] = set()
    try:
        from database_enhanced import get_db
        from db.runtime import execute_query

        conn = get_db()
        rows = execute_query(
            conn,
            """
            SELECT action, details, timestamp
            FROM activity_log
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 40
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        for row in rows:
            action = row["action"] if hasattr(row, "keys") else row[0]
            details = row["details"] if hasattr(row, "keys") else row[1]
            tool = _ACTION_TO_TOOL.get(str(action))
            if not tool:
                continue
            key = tool["href"]
            if key in seen:
                continue
            seen.add(key)
            filters: list[str] = []
            detail_text = str(details or "")
            # Keep chips short and only when details look like filters, not free text dumps.
            if detail_text and len(detail_text) < 80 and "=" not in detail_text:
                filters = [detail_text]
            items.append(
                {
                    "name": tool["name"],
                    "href": tool["href"],
                    "filters": filters,
                }
            )
            if len(items) >= 3:
                break
    except Exception:
        logger.exception("my-day: continue tools failed")

    if not items:
        return {
            "empty": True,
            "message": "Tools you open will show up here.",
            "items": [],
        }
    return {"empty": False, "message": "", "items": items}


def _pin_suggestions(role: str, favorites: list[str]) -> list[dict]:
    fav = {str(x) for x in (favorites or [])}
    out = []
    for item in _ROLE_PIN_SUGGESTIONS["default"]:
        if item["module_id"] in fav:
            continue
        out.append(dict(item))
        if len(out) >= 3:
            break
    return out


def build_my_day(user: dict) -> dict:
    """Build My Day JSON for the authenticated user."""
    user_id = int(user.get("id") or 0)
    username = str(user.get("username") or "").strip()
    role = str(user.get("role") or "").strip().lower()
    prefs = _load_prefs(user_id) if user_id else {}

    favorites_raw = prefs.get("dashboard_favorites") or []
    favorites = [str(x) for x in favorites_raw] if isinstance(favorites_raw, list) else []

    now = datetime.now(timezone.utc)
    last_seen = _parse_ts(prefs.get("my_day_last_seen"))
    # Advance visit anchor only when the previous visit was long enough ago
    # so a same-session refresh keeps the "since last visit" window.
    advance = last_seen is None or (now - last_seen) >= timedelta(hours=2)
    since = last_seen
    if advance:
        _save_prefs_merge(user_id, {"my_day_last_seen": _iso(now)})

    needs = _needs_you(username)
    since_block = _since_last_visit(username, user_id, since)
    watchlist = _watchlist(prefs)
    continue_block = _continue_tools(user_id)

    onboarding_dismissed = bool(prefs.get("my_day_onboarding_dismissed"))
    first_run_show = (not onboarding_dismissed) and (not favorites) and (not watchlist.get("configured"))

    return {
        "greeting_name": username or "there",
        "needs_you": needs,
        "since_last_visit": since_block,
        "watchlist": watchlist,
        "continue": continue_block,
        "pin_suggestions": _pin_suggestions(role, favorites),
        "first_run": {
            "show": first_run_show,
            "steps": [
                {
                    "id": "pin",
                    "title": "Pin Sector Health",
                    "detail": "Keep your daily tools one click away",
                    "href": "/sector-health",
                    "action_label": "Open",
                },
                {
                    "id": "watchlist",
                    "title": "Set a watchlist",
                    "detail": "Cluster, region, or site list you own",
                    "href": "/user-profile",
                    "action_label": "Profile",
                },
                {
                    "id": "case",
                    "title": "Open a case",
                    "detail": "Track work through Optimization Cases",
                    "href": "/optimization-cases",
                    "action_label": "Cases",
                },
            ],
        },
        "favorites_count": len(favorites),
    }
