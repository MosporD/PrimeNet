"""Shared geospatial / cell selection context (server-side per user)."""

from __future__ import annotations

import json
from typing import Any

from core.cases.db import connect, execute, fetchone
from core.cases.schema import init_schema
from core.radio.scoring import utc_now_iso

KINDS = frozenset({"cells", "sites", "polygon", "corridor", "empty"})


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def empty_selection() -> dict:
    return {
        "kind": "empty",
        "cells": [],
        "sites": [],
        "polygon": None,
        "label": "",
        "source": "",
        "updated_at": None,
    }


def normalize_selection(payload: dict | None) -> dict:
    raw = payload or {}
    kind = str(raw.get("kind") or "cells").strip().lower()
    if kind not in KINDS:
        kind = "cells"
    cells = raw.get("cells") or []
    if isinstance(cells, str):
        cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]
    sites = raw.get("sites") or []
    if isinstance(sites, str):
        sites = [s.strip() for s in sites.replace(";", ",").split(",") if s.strip()]
    polygon = raw.get("polygon")
    if polygon is not None and not isinstance(polygon, list):
        polygon = None
    label = str(raw.get("label") or "").strip()
    source = str(raw.get("source") or "").strip()
    if not cells and not sites and not polygon:
        kind = "empty"
    return {
        "kind": kind,
        "cells": [str(c).strip() for c in cells if str(c).strip()][:2000],
        "sites": [str(s).strip() for s in sites if str(s).strip()][:500],
        "polygon": polygon,
        "label": label,
        "source": source,
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
        "updated_at": raw.get("updated_at"),
    }


def get_selection(username: str) -> dict:
    init_schema()
    user = str(username or "").strip()
    if not user:
        return empty_selection()
    with connect() as conn:
        row = fetchone(conn, "SELECT kind, payload_json, updated_at FROM selection_contexts WHERE username = ?", (user,))
    if not row:
        return empty_selection()
    payload = _loads(row.get("payload_json"))
    payload["kind"] = row.get("kind") or payload.get("kind") or "empty"
    payload["updated_at"] = row.get("updated_at")
    return normalize_selection(payload)


def set_selection(username: str, payload: dict | None) -> dict:
    init_schema()
    user = str(username or "").strip()
    if not user:
        raise ValueError("username required")
    selection = normalize_selection(payload)
    now = utc_now_iso()
    selection["updated_at"] = now
    with connect() as conn:
        execute(
            conn,
            """
            INSERT INTO selection_contexts (username, kind, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                kind = excluded.kind,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (user, selection["kind"], _dumps(selection), now),
        )
        conn.commit()
    return selection


def clear_selection(username: str) -> dict:
    return set_selection(username, empty_selection())
