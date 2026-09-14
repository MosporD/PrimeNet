"""Before/after scorecard builder for optimization cases.

V1 is deliberately boring and consistent: same schema for every case.
When post-change PM is unavailable, status is pending with explicit gaps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.cases import config
from core.radio.scoring import utc_now_iso


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _control_neighbors(cells: list[str], limit: int = 5) -> list[str]:
    """Best-effort neighbor names; empty list is OK for V1."""
    if not cells:
        return []
    try:
        from core.radio import neighbor
    except Exception:
        return []
    out: list[str] = []
    seen = {c.lower() for c in cells}
    try:
        # Prefer a lightweight helper if present; otherwise skip.
        if hasattr(neighbor, "sample_neighbors_for_cells"):
            rows = neighbor.sample_neighbors_for_cells(cells, limit=limit)  # type: ignore[attr-defined]
            for row in rows or []:
                name = str(row.get("target") or row.get("cell_name") or "").strip()
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    out.append(name)
                if len(out) >= limit:
                    break
    except Exception:
        return out
    return out


def build_scorecard(
    *,
    cells: list[str] | None = None,
    evidence: dict | None = None,
    facts: list[dict] | None = None,
    execution_ref: str = "",
    executed_at: str | None = None,
    baseline_days: int | None = None,
    post_days: int | None = None,
) -> dict[str, Any]:
    cells_n = [str(c).strip() for c in (cells or []) if str(c).strip()]
    facts = list(facts or [])
    evidence = evidence or {}
    baseline_days = int(baseline_days or config.BASELINE_DAYS)
    post_days = int(post_days or config.POST_DAYS)

    pm_facts = [f for f in facts if f.get("type") == "pm_degradation"]
    cm_facts = [f for f in facts if f.get("type") == "cm_change"]

    anchor = _parse_iso(executed_at)
    if not anchor:
        for f in cm_facts:
            anchor = _parse_iso(str(f.get("changed_at") or ""))
            if anchor:
                break
    if not anchor:
        anchor = datetime.now(timezone.utc)

    baseline_start = (anchor - timedelta(days=baseline_days)).date().isoformat()
    baseline_end = anchor.date().isoformat()
    post_end = (anchor + timedelta(days=post_days)).date().isoformat()
    post_start = anchor.date().isoformat()

    baseline_signals = []
    for f in pm_facts[:10]:
        baseline_signals.append(
            {
                "cell": f.get("cell"),
                "category": f.get("category"),
                "change_pct": f.get("change_pct"),
                "detail": f.get("detail") or {},
            }
        )
    if not baseline_signals and evidence.get("pm_degradation"):
        pm_row = evidence.get("pm_degradation") or {}
        baseline_signals.append(
            {
                "cell": pm_row.get("cell_name"),
                "category": pm_row.get("category"),
                "change_pct": pm_row.get("change_pct"),
                "detail": pm_row,
            }
        )

    has_execution = bool(str(execution_ref or "").strip())
    now = datetime.now(timezone.utc)
    post_elapsed = (now - anchor).total_seconds() / 86400.0
    post_ready = has_execution and post_elapsed >= 1.0

    gaps: list[str] = []
    if not cells_n:
        gaps.append("no_cells")
    if not baseline_signals:
        gaps.append("no_baseline_pm")
    if not has_execution:
        gaps.append("no_execution_ref")
    if has_execution and not post_ready:
        gaps.append("post_window_incomplete")
    if not cm_facts and not evidence.get("change"):
        gaps.append("no_cm_anchor")

    completeness = round(max(0.0, 1.0 - (0.2 * len(gaps))), 2)
    confidence = round(min(1.0, 0.35 + (0.15 * len(baseline_signals)) + (0.2 if has_execution else 0)), 2)

    status = "pending"
    if has_execution and post_ready and baseline_signals:
        status = "ready"
    elif has_execution:
        status = "awaiting_post"
    elif baseline_signals:
        status = "baseline_only"

    rollback_warning = None
    if status == "ready":
        rollback_warning = "Compare post KPIs to baseline; if accessibility/retainability worsen vs control, prepare rollback."
    elif status == "awaiting_post":
        rollback_warning = "Execution recorded but post window is incomplete — do not close the case yet."
    else:
        rollback_warning = "No execution reference — scorecard cannot prove impact yet."

    controls = _control_neighbors(cells_n, limit=config.CONTROL_NEIGHBOR_LIMIT)

    return {
        "generated_at": utc_now_iso(),
        "schema_version": 1,
        "status": status,
        "cells": cells_n,
        "windows": {
            "anchor_at": anchor.isoformat(),
            "baseline_days": baseline_days,
            "post_days": post_days,
            "baseline": {"start": baseline_start, "end": baseline_end},
            "post": {"start": post_start, "end": post_end},
        },
        "baseline": {
            "signals": baseline_signals,
            "signal_count": len(baseline_signals),
        },
        "post": {
            "signals": [],
            "signal_count": 0,
            "ready": post_ready,
            "note": "Post-change KPI pull is scheduled after execution_ref is set (V1 placeholder).",
        },
        "control_neighbors": controls,
        "execution_ref": execution_ref or "",
        "completeness": completeness,
        "confidence": confidence,
        "gaps": gaps,
        "rollback_warning": rollback_warning,
        "verdict": None if status != "ready" else "inconclusive_pending_post_kpis",
    }
