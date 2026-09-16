"""Portal audit trail.

Every state change and every consent/suppression write lands here. The trail
is append-only by convention: nothing in the portal deletes from it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .db import cursor, rows_to_dicts


def record(
    action: str,
    *,
    actor: str | None = None,
    actor_role: str | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    summary: str | None = None,
    detail: dict | None = None,
    conn=None,
) -> None:
    """Append one audit event. Pass ``conn`` to join an open transaction."""
    payload = (
        json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str)
        if detail
        else None
    )
    args = (
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        actor,
        actor_role,
        action,
        entity_type,
        str(entity_id) if entity_id is not None else None,
        summary,
        payload,
    )
    sql = (
        "INSERT INTO audit_event "
        "(occurred_at, actor, actor_role, action, entity_type, entity_id, summary, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    if conn is not None:
        conn.execute(sql, args)
        return
    with cursor() as own:
        own.execute(sql, args)


def record_for(user, action: str, **kwargs) -> None:
    """Convenience wrapper that stamps the acting portal user."""
    kwargs.setdefault("actor", getattr(user, "username", None))
    kwargs.setdefault("actor_role", getattr(user, "role", None))
    record(action, **kwargs)


def recent(limit: int = 100, *, entity_type: str | None = None, entity_id: str | int | None = None) -> list[dict]:
    sql = "SELECT * FROM audit_event"
    where, params = [], []
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if entity_id is not None:
        where.append("entity_id = ?")
        params.append(str(entity_id))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with cursor() as conn:
        rows = conn.execute(sql, params).fetchall()
    events = rows_to_dicts(rows)
    for event in events:
        if event.get("detail"):
            try:
                event["detail"] = json.loads(event["detail"])
            except (TypeError, ValueError):
                pass
    return events
