"""Deterministic evidence correlator for optimization cases.

Collects verified facts only (PM degradation, CM deltas, alarms). AI summarization
is intentionally out of scope — narrative is template-built from facts.
"""

from __future__ import annotations

from typing import Any

from core.radio.scoring import utc_now_iso


def _norm_cells(cells: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for cell in cells or []:
        text = str(cell or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _cell_keys(cells: list[str]) -> set[str]:
    return {c.lower() for c in cells}


def _collect_cm_facts(cells: list[str], *, vendor: str = "", technology: str = "", limit: int = 20) -> list[dict]:
    try:
        from core.radio import cm_store
    except Exception:
        return []
    keys = _cell_keys(cells)
    facts: list[dict] = []
    try:
        changes = cm_store.detect_changes(limit=max(limit * 5, 100))
    except Exception:
        return []
    for ch in changes:
        cell = str(ch.get("cell_name") or "").strip()
        if keys and cell.lower() not in keys:
            continue
        if vendor and vendor.lower() != "all" and str(ch.get("vendor") or "").lower() != vendor.lower():
            continue
        if technology and technology.lower() != "all" and technology.lower() not in str(ch.get("technology") or "").lower():
            continue
        facts.append(
            {
                "type": "cm_change",
                "verified": True,
                "cell": cell,
                "parameter": ch.get("parameter"),
                "old_value": ch.get("old_value"),
                "new_value": ch.get("new_value"),
                "changed_at": ch.get("changed_at"),
                "vendor": ch.get("vendor"),
                "technology": ch.get("technology"),
                "site_id": ch.get("site_id"),
            }
        )
        if len(facts) >= limit:
            break
    return facts


def _collect_pm_facts(cells: list[str], *, vendor: str = "all", technology: str = "all", limit: int = 20) -> list[dict]:
    try:
        from core.radio import pm
    except Exception:
        return []
    keys = _cell_keys(cells)
    facts: list[dict] = []
    techs = ["2G", "3G", "4G", "5G"] if technology in ("", "all", None) else [str(technology).split("-")[0]]
    try:
        for tech in techs:
            family = "4G" if str(tech).upper().startswith("4G") else str(tech)
            rows = pm.degraded_cells(vendor=vendor if vendor else "all", technology=family, limit=300)
            for row in rows:
                cell = str(row.get("cell_name") or "").strip()
                if keys and cell.lower() not in keys:
                    continue
                facts.append(
                    {
                        "type": "pm_degradation",
                        "verified": True,
                        "cell": cell,
                        "category": row.get("category"),
                        "change_pct": row.get("change_pct"),
                        "vendor": row.get("vendor") or vendor,
                        "technology": row.get("technology") or family,
                        "area": row.get("area"),
                        "detail": {
                            k: row.get(k)
                            for k in ("kpi", "value", "baseline", "score")
                            if row.get(k) is not None
                        },
                    }
                )
                if len(facts) >= limit:
                    return facts
    except Exception:
        return facts
    return facts


def _collect_alarm_facts(cells: list[str], *, limit: int = 15) -> list[dict]:
    if not cells:
        return []
    try:
        from core.radio import alarm_join
    except Exception:
        return []
    facts: list[dict] = []
    try:
        matched = alarm_join.match_alarms_for_cells(cells, [])
    except Exception:
        return []
    for cell in cells:
        hits = matched.get(cell.lower()) or []
        for alarm in hits[:3]:
            facts.append(
                {
                    "type": "alarm",
                    "verified": True,
                    "cell": cell,
                    "alarm_name": alarm.get("alarm_name") or alarm.get("probable_cause"),
                    "severity": alarm.get("severity") or alarm.get("perceived_severity"),
                    "occurred_at": alarm.get("event_time") or alarm.get("alarm_time"),
                }
            )
            if len(facts) >= limit:
                return facts
    return facts


def build_narrative(facts: list[dict], *, cells: list[str], title: str = "") -> str:
    """One-page deterministic narrative from verified facts only."""
    cm = [f for f in facts if f.get("type") == "cm_change"]
    pm = [f for f in facts if f.get("type") == "pm_degradation"]
    alarms = [f for f in facts if f.get("type") == "alarm"]
    cell_label = ", ".join(cells[:5]) + ("…" if len(cells) > 5 else "")
    lines = [
        f"What: {title or 'Optimization investigation'} for {cell_label or 'selected cells'}.",
        f"Where: {len(cells)} cell(s) in scope.",
    ]
    if pm:
        cats = sorted({str(f.get("category") or "KPI") for f in pm})
        lines.append(
            f"PM: {len(pm)} degradation signal(s) — categories: {', '.join(cats)}."
        )
    else:
        lines.append("PM: no matching degradation rows in the current degraded-cell scan.")
    if cm:
        params = sorted({str(f.get("parameter") or "?") for f in cm})[:5]
        lines.append(
            f"CM: {len(cm)} recent parameter change(s) — {', '.join(params)}."
        )
    else:
        lines.append("CM: no recent snapshot deltas matched these cells.")
    if alarms:
        names = sorted({str(f.get("alarm_name") or "alarm") for f in alarms})[:4]
        lines.append(f"FM: {len(alarms)} alarm hit(s) — {', '.join(names)}.")
    else:
        lines.append("FM: no matching live alarms for these cells in the current window.")

    if pm and cm:
        lines.append("Likely why: PM degradation coincides with recent CM deltas — treat as change-impact candidate.")
    elif alarms and pm:
        lines.append("Likely why: PM collapse with alarms — treat as fault/outage before RF optimization.")
    elif pm:
        lines.append("Likely why: PM degradation without matched CM/FM — check neighbors, coverage, and capacity.")
    elif cm:
        lines.append("Likely why: CM changed without confirmed PM hit yet — monitor before/after windows.")
    else:
        lines.append("Likely why: insufficient correlated evidence — gather more PM/CM/FM before acting.")

    do_bits = []
    if alarms:
        do_bits.append("clear/ack alarms first")
    if cm:
        do_bits.append("review CM delta vs golden rules")
    if pm:
        do_bits.append("confirm KPI before/after windows")
    do_bits.append("propose change only after evidence review")
    lines.append("Do: " + "; ".join(do_bits) + ".")
    return "\n".join(lines)


def correlate_evidence(
    *,
    cells: list[str] | None = None,
    vendor: str = "",
    technology: str = "",
    area: str = "",
    title: str = "",
    seed_evidence: dict | None = None,
    include_alarms: bool = True,
) -> dict[str, Any]:
    cells_n = _norm_cells(cells)
    facts: list[dict] = []

    if seed_evidence:
        facts.append(
            {
                "type": "source_issue",
                "verified": True,
                "payload": seed_evidence,
            }
        )

    facts.extend(_collect_cm_facts(cells_n, vendor=vendor, technology=technology))
    facts.extend(_collect_pm_facts(cells_n, vendor=vendor or "all", technology=technology or "all"))
    if include_alarms:
        facts.extend(_collect_alarm_facts(cells_n))

    verified = [f for f in facts if f.get("verified")]
    confidence = 0.2
    types = {f.get("type") for f in verified}
    if "pm_degradation" in types:
        confidence += 0.3
    if "cm_change" in types:
        confidence += 0.25
    if "alarm" in types:
        confidence += 0.15
    if len(cells_n) > 0:
        confidence += 0.1
    confidence = round(min(1.0, confidence), 2)

    narrative = build_narrative(verified, cells=cells_n, title=title)
    return {
        "generated_at": utc_now_iso(),
        "cells": cells_n,
        "area": area or "",
        "vendor": vendor or "",
        "technology": technology or "",
        "facts": verified,
        "fact_counts": {
            "cm_change": sum(1 for f in verified if f.get("type") == "cm_change"),
            "pm_degradation": sum(1 for f in verified if f.get("type") == "pm_degradation"),
            "alarm": sum(1 for f in verified if f.get("type") == "alarm"),
            "source_issue": sum(1 for f in verified if f.get("type") == "source_issue"),
            "total": len(verified),
        },
        "confidence": confidence,
        "narrative": narrative,
    }
