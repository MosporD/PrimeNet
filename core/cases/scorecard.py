"""Before/after scorecard builder for optimization cases.

Pulls live PM degradation signals for case cells when execution_ref is set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.cases import config, identity
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
    if not cells:
        return []
    try:
        from core.radio import neighbor
    except Exception:
        return []
    out: list[str] = []
    seen = {identity.normalize_cell_key(c) for c in cells}
    try:
        if hasattr(neighbor, "sample_neighbors_for_cells"):
            rows = neighbor.sample_neighbors_for_cells(cells, limit=limit)  # type: ignore[attr-defined]
            for row in rows or []:
                name = str(row.get("target") or row.get("cell_name") or "").strip()
                key = identity.normalize_cell_key(name)
                if name and key and key not in seen:
                    seen.add(key)
                    out.append(name)
                if len(out) >= limit:
                    break
        elif hasattr(neighbor, "load_neighbor_lines"):
            lines = neighbor.load_neighbor_lines(max_lines=400)
            cell_set = set()
            for c in cells:
                cell_set |= identity.cell_aliases(c)
            for line in lines or []:
                src = str(line.get("source_cell") or line.get("source") or "")
                tgt = str(line.get("target_cell") or line.get("target") or "")
                if identity.cell_aliases(src) & cell_set:
                    key = identity.normalize_cell_key(tgt)
                    if tgt and key and key not in seen:
                        seen.add(key)
                        out.append(tgt)
                if len(out) >= limit:
                    break
    except Exception:
        return out
    return out


def _signal_from_pm_row(row: dict) -> dict:
    return {
        "cell": row.get("cell_name") or row.get("cell"),
        "category": row.get("category"),
        "change_pct": row.get("change_pct"),
        "today_value": row.get("today_value"),
        "week_avg": row.get("week_avg"),
        "kpi_column": row.get("kpi_column"),
        "direction": row.get("direction"),
        "breached": row.get("breached"),
        "score": row.get("score"),
        "detail": {
            k: row.get(k)
            for k in ("today_value", "week_avg", "change_pct", "kpi_column", "latest_day")
            if row.get(k) is not None
        },
    }


def _pull_pm_signals(
    cells: list[str],
    *,
    vendor: str = "all",
    technology: str = "4G",
    limit: int = 40,
) -> list[dict]:
    """Best-effort current PM degradation rows for case cells."""
    if not cells:
        return []
    try:
        from core.radio import pm
    except Exception:
        return []
    tech = technology if technology and technology.lower() != "all" else "4G"
    family = "4G" if str(tech).upper().startswith("4G") else str(tech).split("-")[0] or "4G"
    vend = vendor if vendor and vendor.lower() != "all" else "all"
    try:
        rows = pm.degraded_cells(vendor=vend, technology=family, limit=max(limit * 5, 200))
    except Exception:
        return []
    matched = identity.filter_rows_for_cells(rows, cells, cell_field="cell_name")
    return [_signal_from_pm_row(r) for r in matched[:limit]]


def _avg_change(signals: list[dict]) -> float | None:
    vals = []
    for s in signals:
        try:
            if s.get("change_pct") is not None:
                vals.append(float(s["change_pct"]))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    return sum(vals) / len(vals)


def _verdict_from_signals(baseline: list[dict], post: list[dict], controls: list[dict]) -> str:
    """improve / worsen / flat / inconclusive."""
    b = _avg_change(baseline)
    p = _avg_change(post)
    if b is None and not post:
        return "inconclusive"
    if not post:
        return "inconclusive"
    if b is None:
        # Only post: if still degrading badly → worsen, else inconclusive
        if p is not None and abs(p) >= 5:
            return "worsen"
        return "inconclusive"
    # For higher_worse style change_pct, lower magnitude after fix is improve
    delta = (p if p is not None else 0) - b
    if abs(delta) < 2.0:
        c = _avg_change(controls)
        if c is not None and p is not None and abs(p) <= abs(c) + 1:
            return "flat"
        return "flat"
    # Improvement = post change_pct less severe than baseline (closer to 0 or better)
    if abs(p if p is not None else 0) + 2 < abs(b):
        return "improve"
    if abs(p if p is not None else 0) > abs(b) + 2:
        return "worsen"
    return "flat"


def build_scorecard(
    *,
    cells: list[str] | None = None,
    evidence: dict | None = None,
    facts: list[dict] | None = None,
    execution_ref: str = "",
    executed_at: str | None = None,
    baseline_days: int | None = None,
    post_days: int | None = None,
    vendor: str = "",
    technology: str = "",
    pull_pm: bool = True,
) -> dict[str, Any]:
    cells_n = identity.expand_cell_list(cells)
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

    baseline_signals: list[dict] = []
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
        baseline_signals.append(_signal_from_pm_row(pm_row))

    has_execution = bool(str(execution_ref or "").strip())
    now = datetime.now(timezone.utc)
    post_elapsed = (now - anchor).total_seconds() / 86400.0
    post_ready = has_execution and post_elapsed >= 0.0  # allow same-day pull after execute

    controls = _control_neighbors(cells_n, limit=config.CONTROL_NEIGHBOR_LIMIT)

    post_signals: list[dict] = []
    control_signals: list[dict] = []
    pm_note = "Post-change KPI pull runs when execution_ref is set."
    if pull_pm and has_execution and cells_n:
        try:
            post_signals = _pull_pm_signals(
                cells_n, vendor=vendor or "all", technology=technology or "4G"
            )
            if controls:
                control_signals = _pull_pm_signals(
                    controls, vendor=vendor or "all", technology=technology or "4G", limit=20
                )
            if post_signals:
                pm_note = f"Pulled {len(post_signals)} post PM signal(s) for case cells."
            else:
                pm_note = "execution_ref set but no matching degraded-cell PM rows for case cells."
                if "no_post_pm" not in []:
                    pass
        except Exception as exc:
            pm_note = f"PM pull failed: {exc}"

    # If we have execution but no baseline facts, use current pull as baseline snapshot once
    if has_execution and not baseline_signals and post_signals:
        baseline_signals = list(post_signals)

    gaps: list[str] = []
    if not cells_n:
        gaps.append("no_cells")
    if not baseline_signals:
        gaps.append("no_baseline_pm")
    if not has_execution:
        gaps.append("no_execution_ref")
    if has_execution and not post_signals:
        gaps.append("no_post_pm")
    if not cm_facts and not evidence.get("change"):
        gaps.append("no_cm_anchor")

    completeness = round(max(0.0, 1.0 - (0.15 * len(gaps))), 2)
    confidence = round(
        min(
            1.0,
            0.3
            + (0.15 * min(3, len(baseline_signals)))
            + (0.2 if has_execution else 0)
            + (0.2 if post_signals else 0),
        ),
        2,
    )

    status = "pending"
    if has_execution and post_signals:
        status = "ready"
    elif has_execution:
        status = "awaiting_post"
    elif baseline_signals:
        status = "baseline_only"

    verdict = None
    if status == "ready":
        verdict = _verdict_from_signals(baseline_signals, post_signals, control_signals)

    if status == "ready":
        if verdict == "worsen":
            rollback_warning = "Post KPIs look worse than baseline — prepare rollback."
        elif verdict == "improve":
            rollback_warning = "Post KPIs improved vs baseline — verify control neighbors before closing."
        else:
            rollback_warning = "Post KPIs inconclusive/flat — keep monitoring before close."
    elif status == "awaiting_post":
        rollback_warning = "Execution recorded but post PM signals missing — do not close yet."
    else:
        rollback_warning = "No execution reference — scorecard cannot prove impact yet."

    return {
        "generated_at": utc_now_iso(),
        "schema_version": 2,
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
            "avg_change_pct": _avg_change(baseline_signals),
        },
        "post": {
            "signals": post_signals,
            "signal_count": len(post_signals),
            "avg_change_pct": _avg_change(post_signals),
            "ready": bool(post_signals),
            "note": pm_note,
        },
        "control_neighbors": controls,
        "control": {
            "signals": control_signals,
            "signal_count": len(control_signals),
            "avg_change_pct": _avg_change(control_signals),
        },
        "execution_ref": execution_ref or "",
        "completeness": completeness,
        "confidence": confidence,
        "gaps": gaps,
        "rollback_warning": rollback_warning,
        "verdict": verdict,
    }
