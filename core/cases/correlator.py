"""Deterministic evidence correlator for optimization cases."""

from __future__ import annotations

from typing import Any

from core.cases import identity
from core.radio.scoring import utc_now_iso


def _norm_cells(cells: list[str] | None) -> list[str]:
    return identity.expand_cell_list(cells)


def _collect_cm_facts(cells: list[str], *, vendor: str = "", technology: str = "", limit: int = 20) -> list[dict]:
    try:
        from core.radio import cm_store
    except Exception:
        return []
    facts: list[dict] = []
    try:
        changes = cm_store.detect_changes(limit=max(limit * 5, 100))
    except Exception:
        return []
    for ch in identity.filter_rows_for_cells(changes, cells, cell_field="cell_name"):
        if vendor and vendor.lower() != "all" and str(ch.get("vendor") or "").lower() != vendor.lower():
            continue
        if technology and technology.lower() != "all" and technology.lower() not in str(ch.get("technology") or "").lower():
            continue
        facts.append(
            {
                "type": "cm_change",
                "verified": True,
                "cell": ch.get("cell_name"),
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
    facts: list[dict] = []
    techs = ["2G", "3G", "4G", "5G"] if technology in ("", "all", None) else [str(technology).split("-")[0]]
    try:
        for tech in techs:
            family = "4G" if str(tech).upper().startswith("4G") else str(tech)
            rows = pm.degraded_cells(vendor=vendor if vendor else "all", technology=family, limit=300)
            for row in identity.filter_rows_for_cells(rows, cells, cell_field="cell_name"):
                facts.append(
                    {
                        "type": "pm_degradation",
                        "verified": True,
                        "cell": row.get("cell_name"),
                        "category": row.get("category"),
                        "change_pct": row.get("change_pct"),
                        "vendor": row.get("vendor") or vendor,
                        "technology": row.get("technology") or family,
                        "area": row.get("area"),
                        "detail": {
                            k: row.get(k)
                            for k in ("kpi", "kpi_column", "value", "today_value", "week_avg", "baseline", "score")
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
        for key in identity.cell_aliases(cell):
            hits = matched.get(key) or []
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


def _collect_neighbor_facts(cells: list[str], *, vendor: str = "all", technology: str = "all", limit: int = 15) -> list[dict]:
    if not cells:
        return []
    try:
        from core.radio import neighbor
    except Exception:
        return []
    facts: list[dict] = []
    try:
        lines = neighbor.load_neighbor_lines(
            vendor=vendor if vendor else "all",
            technology=technology if technology and technology.lower() != "all" else "4G-4G",
            min_attempts=5,
            max_lines=400,
        )
    except Exception:
        return []
    targets = set()
    for c in cells:
        targets |= identity.cell_aliases(c)
    for line in lines or []:
        src = str(line.get("source_cell") or line.get("source") or line.get("source_name") or "")
        tgt = str(line.get("target_cell") or line.get("target") or line.get("target_name") or "")
        if not (identity.cell_aliases(src) & targets or identity.cell_aliases(tgt) & targets):
            continue
        att = line.get("attempts") or line.get("ho_attempts") or line.get("NB_ATT")
        fail = line.get("failures") or line.get("ho_failures") or line.get("NB_FAIL")
        defined = line.get("defined")
        if defined is None:
            defined = line.get("NB_DEFINED")
        missing = defined in (0, "0", False, "false", "False")
        facts.append(
            {
                "type": "neighbor_quality",
                "verified": True,
                "source": src,
                "target": tgt,
                "attempts": att,
                "failures": fail,
                "missing_neighbor": missing,
                "distance_km": line.get("distance_km") or line.get("distance"),
            }
        )
        if len(facts) >= limit:
            break
    return facts


def _collect_overshoot_facts(cells: list[str], seed_evidence: dict | None, source_module: str = "") -> list[dict]:
    """Attach overshoot template facts from seed evidence when source is overshooting."""
    mod = (source_module or "").lower()
    seed = seed_evidence or {}
    if "overshoot" not in mod and "overshoot" not in str(seed.get("category") or "").lower():
        keys = set(seed.keys()) if isinstance(seed, dict) else set()
        if not keys.intersection({"propagation_delay", "timing_advance", "pd", "ta", "ul_interference"}):
            return []
    facts = []
    for cell in cells[:5]:
        facts.append(
            {
                "type": "overshoot_pack",
                "verified": True,
                "cell": cell,
                "propagation_delay": seed.get("propagation_delay") or seed.get("pd"),
                "timing_advance": seed.get("timing_advance") or seed.get("ta"),
                "ul_interference": seed.get("ul_interference") or seed.get("ul_noise"),
                "far_ho_attempts": seed.get("far_ho_attempts"),
                "note": "Overshoot evidence pack — confirm PD/TA reach + far missing neighbors before downtilt.",
            }
        )
    return facts


def build_narrative(facts: list[dict], *, cells: list[str], title: str = "") -> str:
    cm = [f for f in facts if f.get("type") == "cm_change"]
    pm = [f for f in facts if f.get("type") == "pm_degradation"]
    alarms = [f for f in facts if f.get("type") == "alarm"]
    nb = [f for f in facts if f.get("type") == "neighbor_quality"]
    ov = [f for f in facts if f.get("type") == "overshoot_pack"]
    cell_label = ", ".join(cells[:5]) + ("…" if len(cells) > 5 else "")
    lines = [
        f"What: {title or 'Optimization investigation'} for {cell_label or 'selected cells'}.",
        f"Where: {len(cells)} cell(s) in scope.",
    ]
    if pm:
        cats = sorted({str(f.get("category") or "KPI") for f in pm})
        lines.append(f"PM: {len(pm)} degradation signal(s) — categories: {', '.join(cats)}.")
    else:
        lines.append("PM: no matching degradation rows in the current degraded-cell scan.")
    if cm:
        params = sorted({str(f.get("parameter") or "?") for f in cm})[:5]
        lines.append(f"CM: {len(cm)} recent parameter change(s) — {', '.join(params)}.")
    else:
        lines.append("CM: no recent snapshot deltas matched these cells.")
    if alarms:
        names = sorted({str(f.get("alarm_name") or "alarm") for f in alarms})[:4]
        lines.append(f"FM: {len(alarms)} alarm hit(s) — {', '.join(names)}.")
    else:
        lines.append("FM: no matching live alarms for these cells in the current window.")
    if nb:
        missing = sum(1 for f in nb if f.get("missing_neighbor"))
        lines.append(f"Neighbors: {len(nb)} relation(s) inspected; missing-defined flag on {missing}.")
    if ov:
        lines.append(f"Overshoot pack: {len(ov)} cell template(s) attached — verify PD/TA + far HO.")

    if pm and cm:
        lines.append("Likely why: PM degradation coincides with recent CM deltas — treat as change-impact candidate.")
    elif alarms and pm:
        lines.append("Likely why: PM collapse with alarms — treat as fault/outage before RF optimization.")
    elif ov or (nb and any(f.get("missing_neighbor") for f in nb)):
        lines.append("Likely why: coverage/neighbor footprint issue — check overshoot and missing neighbors.")
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
    if ov or nb:
        do_bits.append("validate neighbor/overshoot on map")
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
    source_module: str = "",
) -> dict[str, Any]:
    cells_n = _norm_cells(cells)
    facts: list[dict] = []

    if seed_evidence:
        facts.append({"type": "source_issue", "verified": True, "payload": seed_evidence})

    facts.extend(_collect_cm_facts(cells_n, vendor=vendor, technology=technology))
    facts.extend(_collect_pm_facts(cells_n, vendor=vendor or "all", technology=technology or "all"))
    if include_alarms:
        facts.extend(_collect_alarm_facts(cells_n))
    facts.extend(_collect_neighbor_facts(cells_n, vendor=vendor or "all", technology=technology or "all"))
    facts.extend(_collect_overshoot_facts(cells_n, seed_evidence if isinstance(seed_evidence, dict) else {}, source_module))

    verified = [f for f in facts if f.get("verified")]
    confidence = 0.2
    types = {f.get("type") for f in verified}
    if "pm_degradation" in types:
        confidence += 0.25
    if "cm_change" in types:
        confidence += 0.2
    if "alarm" in types:
        confidence += 0.15
    if "neighbor_quality" in types:
        confidence += 0.1
    if "overshoot_pack" in types:
        confidence += 0.1
    if cells_n:
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
            "neighbor_quality": sum(1 for f in verified if f.get("type") == "neighbor_quality"),
            "overshoot_pack": sum(1 for f in verified if f.get("type") == "overshoot_pack"),
            "source_issue": sum(1 for f in verified if f.get("type") == "source_issue"),
            "total": len(verified),
        },
        "confidence": confidence,
        "narrative": narrative,
    }
