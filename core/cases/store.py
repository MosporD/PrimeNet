"""CRUD + state machine for optimization cases."""

from __future__ import annotations

import json
import uuid
from typing import Any

from core.cases import config
from core.cases.db import connect, execute, fetchall, fetchone
from core.cases.schema import init_schema
from core.radio.scoring import utc_now_iso


class CaseError(ValueError):
    pass


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _loads(raw: str | None, default: Any):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _row_to_case(row: dict) -> dict:
    return {
        "case_id": row["case_id"],
        "title": row["title"],
        "summary": row.get("summary") or "",
        "state": row.get("state") or "open",
        "severity": row.get("severity") or "Medium",
        "score": float(row.get("score") or 0),
        "impact_score": float(row.get("impact_score") or 0),
        "category": row.get("category") or "",
        "source_module": row.get("source_module") or "",
        "source_issue_id": row.get("source_issue_id") or "",
        "source_url": row.get("source_url") or "",
        "vendor": row.get("vendor") or "",
        "technology": row.get("technology") or "",
        "area": row.get("area") or "",
        "site_id": row.get("site_id") or "",
        "ticket_id": row.get("ticket_id") or "",
        "owner": row.get("owner") or "",
        "created_by": row.get("created_by") or "",
        "recommendation": row.get("recommendation") or "",
        "proposed_change": row.get("proposed_change") or "",
        "execution_ref": row.get("execution_ref") or "",
        "narrative": row.get("narrative") or "",
        "evidence": _loads(row.get("evidence_json"), {}),
        "cells": _loads(row.get("cells_json"), []),
        "selection": _loads(row.get("selection_json"), {}),
        "scorecard": _loads(row.get("scorecard_json"), {}),
        "checklist": _loads(row.get("checklist_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"),
    }


def _append_event(conn, case_id: str, event_type: str, actor: str = "", detail: dict | None = None) -> None:
    execute(
        conn,
        """
        INSERT INTO opt_case_events (case_id, event_type, actor, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (case_id, event_type, actor or "", _dumps(detail or {}), utc_now_iso()),
    )


def create_case(payload: dict, *, actor: str = "") -> dict:
    init_schema()
    case_id = str(payload.get("case_id") or uuid.uuid4().hex[:12])
    now = utc_now_iso()
    state = str(payload.get("state") or "open")
    if state not in config.STATES:
        raise CaseError(f"Invalid state: {state}")

    cells = payload.get("cells") or []
    if isinstance(cells, str):
        cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]

    row = {
        "case_id": case_id,
        "title": str(payload.get("title") or "Untitled case").strip() or "Untitled case",
        "summary": str(payload.get("summary") or ""),
        "state": state,
        "severity": str(payload.get("severity") or "Medium"),
        "score": float(payload.get("score") or 0),
        "impact_score": float(payload.get("impact_score") or 0),
        "category": str(payload.get("category") or ""),
        "source_module": str(payload.get("source_module") or ""),
        "source_issue_id": str(payload.get("source_issue_id") or ""),
        "source_url": str(payload.get("source_url") or ""),
        "vendor": str(payload.get("vendor") or ""),
        "technology": str(payload.get("technology") or ""),
        "area": str(payload.get("area") or ""),
        "site_id": str(payload.get("site_id") or ""),
        "ticket_id": str(payload.get("ticket_id") or ""),
        "owner": str(payload.get("owner") or actor or ""),
        "created_by": str(payload.get("created_by") or actor or ""),
        "recommendation": str(payload.get("recommendation") or ""),
        "proposed_change": str(payload.get("proposed_change") or ""),
        "execution_ref": str(payload.get("execution_ref") or ""),
        "narrative": str(payload.get("narrative") or ""),
        "evidence_json": _dumps(payload.get("evidence") or {}),
        "cells_json": _dumps(list(cells)),
        "selection_json": _dumps(payload.get("selection") or {}),
        "scorecard_json": _dumps(payload.get("scorecard") or {}),
        "checklist_json": _dumps(payload.get("checklist") or {}),
        "created_at": now,
        "updated_at": now,
        "closed_at": None,
    }

    with connect() as conn:
        execute(
            conn,
            """
            INSERT INTO opt_cases (
                case_id, title, summary, state, severity, score, impact_score, category,
                source_module, source_issue_id, source_url, vendor, technology,
                area, site_id, ticket_id, owner, created_by, recommendation, proposed_change,
                execution_ref, narrative, evidence_json, cells_json, selection_json,
                scorecard_json, checklist_json, created_at, updated_at, closed_at
            ) VALUES (
                :case_id, :title, :summary, :state, :severity, :score, :impact_score, :category,
                :source_module, :source_issue_id, :source_url, :vendor, :technology,
                :area, :site_id, :ticket_id, :owner, :created_by, :recommendation, :proposed_change,
                :execution_ref, :narrative, :evidence_json, :cells_json, :selection_json,
                :scorecard_json, :checklist_json, :created_at, :updated_at, :closed_at
            )
            """,
            row,
        )
        _append_event(conn, case_id, "created", actor=actor, detail={"state": state, "title": row["title"]})
        conn.commit()
    return get_case(case_id)


def get_case(case_id: str) -> dict | None:
    init_schema()
    with connect() as conn:
        row = fetchone(conn, "SELECT * FROM opt_cases WHERE case_id = ?", (case_id,))
    return _row_to_case(row) if row else None


def list_cases(
    *,
    state: str = "",
    owner: str = "",
    search: str = "",
    limit: int = 100,
) -> list[dict]:
    init_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if state and state.lower() != "all":
        clauses.append("state = ?")
        params.append(state)
    if owner:
        clauses.append("owner = ?")
        params.append(owner)
    if search:
        like = f"%{search.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR cells_json LIKE ? OR area LIKE ?)")
        params.extend([like, like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(int(limit or 100), 500)))
    with connect() as conn:
        rows = fetchall(
            conn,
            f"SELECT * FROM opt_cases {where} ORDER BY impact_score DESC, updated_at DESC LIMIT ?",
            params,
        )
    return [_row_to_case(r) for r in rows]


def list_events(case_id: str, *, limit: int = 50) -> list[dict]:
    init_schema()
    with connect() as conn:
        rows = fetchall(
            conn,
            """
            SELECT event_id, case_id, event_type, actor, detail_json, created_at
            FROM opt_case_events
            WHERE case_id = ?
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (case_id, max(1, min(int(limit or 50), 200))),
        )
    out = []
    for row in rows:
        out.append(
            {
                "event_id": row["event_id"],
                "case_id": row["case_id"],
                "event_type": row["event_type"],
                "actor": row.get("actor") or "",
                "detail": _loads(row.get("detail_json"), {}),
                "created_at": row.get("created_at"),
            }
        )
    return out


def update_case(case_id: str, patch: dict, *, actor: str = "") -> dict:
    init_schema()
    current = get_case(case_id)
    if not current:
        raise CaseError(f"Case not found: {case_id}")

    allowed = {
        "title",
        "summary",
        "severity",
        "score",
        "impact_score",
        "category",
        "vendor",
        "technology",
        "area",
        "site_id",
        "ticket_id",
        "owner",
        "recommendation",
        "proposed_change",
        "execution_ref",
        "narrative",
        "evidence",
        "cells",
        "selection",
        "scorecard",
        "checklist",
        "source_url",
    }
    fields: dict[str, Any] = {}
    for key, value in (patch or {}).items():
        if key not in allowed:
            continue
        if key in ("evidence", "selection", "scorecard", "checklist"):
            fields[f"{key}_json"] = _dumps(value or {})
        elif key == "cells":
            cells = value or []
            if isinstance(cells, str):
                cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]
            fields["cells_json"] = _dumps(list(cells))
        else:
            fields[key] = value

    if not fields:
        return current

    fields["updated_at"] = utc_now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [case_id]
    with connect() as conn:
        execute(conn, f"UPDATE opt_cases SET {sets} WHERE case_id = ?", params)
        _append_event(conn, case_id, "updated", actor=actor, detail={"fields": list(fields.keys())})
        conn.commit()
    return get_case(case_id)  # type: ignore[return-value]


def transition_case(
    case_id: str,
    new_state: str,
    *,
    actor: str = "",
    note: str = "",
    override_note: str = "",
) -> dict:
    init_schema()
    current = get_case(case_id)
    if not current:
        raise CaseError(f"Case not found: {case_id}")
    new_state = str(new_state or "").strip().lower()
    if new_state not in config.STATES:
        raise CaseError(f"Invalid state: {new_state}")
    old = current["state"]
    allowed = config.TRANSITIONS.get(old, frozenset())
    if new_state not in allowed:
        raise CaseError(f"Cannot transition {old} → {new_state}")

    if new_state == "approved":
        from core.cases.gates import assert_can_approve

        assert_can_approve(current, override_note=override_note or note)

    now = utc_now_iso()
    closed_at = now if new_state in ("closed", "rejected") else None
    with connect() as conn:
        execute(
            conn,
            """
            UPDATE opt_cases
            SET state = ?, updated_at = ?, closed_at = COALESCE(?, closed_at)
            WHERE case_id = ?
            """,
            (new_state, now, closed_at, case_id),
        )
        _append_event(
            conn,
            case_id,
            "transition",
            actor=actor,
            detail={
                "from": old,
                "to": new_state,
                "note": note or "",
                "override_note": override_note or "",
            },
        )
        conn.commit()
    case = get_case(case_id)
    if case and new_state in ("verifying", "closed") and (case.get("scorecard") or {}).get("verdict"):
        try:
            from core.cases import treatments

            treatments.record_outcome(
                title=case.get("recommendation") or case.get("title") or "",
                category=case.get("category") or "",
                verdict=str((case.get("scorecard") or {}).get("verdict") or ""),
                meta={"case_id": case_id},
            )
        except Exception:
            pass
    return case  # type: ignore[return-value]


def set_scorecard(case_id: str, scorecard: dict, *, actor: str = "") -> dict:
    return update_case(case_id, {"scorecard": scorecard}, actor=actor)


def find_by_source_issue(source_issue_id: str, *, within_days: int = 7) -> dict | None:
    """Most recent case with this source_issue_id within N days (dedupe helper)."""
    init_schema()
    sid = str(source_issue_id or "").strip()
    if not sid:
        return None
    with connect() as conn:
        row = fetchone(
            conn,
            """
            SELECT * FROM opt_cases
            WHERE source_issue_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sid,),
        )
    if not row:
        return None
    case = _row_to_case(row)
    created = case.get("created_at") or ""
    try:
        from datetime import datetime, timedelta, timezone

        text = created.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - dt.astimezone(timezone.utc) > timedelta(days=max(1, within_days)):
            return None
    except ValueError:
        pass
    return case


def find_related_by_cells(
    cells: list[str],
    *,
    exclude_case_id: str = "",
    within_days: int = 30,
    limit: int = 20,
) -> list[dict]:
    """Other cases sharing any cell alias in the last N days."""
    from datetime import datetime, timedelta, timezone

    from core.cases import identity

    init_schema()
    targets: set[str] = set()
    for c in cells or []:
        targets |= identity.cell_aliases(c)
    if not targets:
        return []
    rows = list_cases(limit=300)
    out: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, within_days))
    for case in rows:
        if exclude_case_id and case.get("case_id") == exclude_case_id:
            continue
        if case.get("updated_at"):
            try:
                text = str(case["updated_at"]).replace("Z", "+00:00")
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.astimezone(timezone.utc) < cutoff:
                    continue
            except Exception:
                pass
        overlap = False
        for oc in case.get("cells") or []:
            if identity.cell_aliases(oc) & targets:
                overlap = True
                break
        if overlap:
            out.append(
                {
                    "case_id": case.get("case_id"),
                    "title": case.get("title"),
                    "state": case.get("state"),
                    "severity": case.get("severity"),
                    "updated_at": case.get("updated_at"),
                    "source_module": case.get("source_module"),
                }
            )
        if len(out) >= limit:
            break
    return out


def case_stats() -> dict:
    init_schema()
    with connect() as conn:
        rows = fetchall(conn, "SELECT state, COUNT(*) AS n FROM opt_cases GROUP BY state")
        total = fetchone(conn, "SELECT COUNT(*) AS n FROM opt_cases")
    by_state = {r["state"]: int(r["n"]) for r in rows}
    return {"total": int((total or {}).get("n") or 0), "by_state": by_state}
