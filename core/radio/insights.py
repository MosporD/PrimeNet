"""Cross-module radio insight builders."""

from __future__ import annotations

from modules.reports.sector_coverage_data import build_sector_coverage_payload

from . import cm_store, metadata, neighbor, pm
from .scoring import bounded_score, filter_rows, issue, summarize, to_float, utc_now_iso


def _limit(rows: list[dict], limit: int) -> list[dict]:
    return rows[: max(1, min(1000, int(limit or 200)))]


def capacity_hotspots(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 200) -> dict:
    util_rows = pm.top_kpi_rows(recipe="utilization", vendor=vendor, rat=technology, top_n=limit, sort_mode="increased")
    cell_meta = metadata.cell_index()
    issues: list[dict] = []
    for row in util_rows:
        cell = str(row.get("cell_name") or "").strip()
        meta = cell_meta.get(cell.lower(), {})
        if area and area.lower() != "all" and str(meta.get("area") or "").lower() != area.lower():
            continue
        delta = abs(float(row.get("delta") or 0))
        post = to_float(row.get("post"))
        score = bounded_score(min(45, delta * 2), max(0, (post or 0) - 70) * 1.2)
        if score < 20:
            continue
        issues.append(issue(
            module="Capacity Hotspots",
            category="Capacity",
            title=f"Capacity pressure on {cell}",
            summary=f"{row.get('kpi')} latest={row.get('post')} vs baseline={row.get('pre')} (delta {row.get('delta')}).",
            score=score,
            cells=[cell],
            site_id=str(meta.get("site_id") or row.get("site_id") or ""),
            area=str(meta.get("area") or row.get("area") or ""),
            vendor=str(row.get("vendor") or meta.get("vendor") or ""),
            technology=str(row.get("technology") or meta.get("technology") or ""),
            evidence={"kpi": row.get("kpi"), "pre": row.get("pre"), "post": row.get("post"), "delta": row.get("delta")},
            recommendation="Review busy-hour PRB/utilization, traffic growth, users, and sector split or carrier expansion options.",
            source_url="/capacity-hotspots",
        ))
    rows = _limit(sorted(issues, key=lambda r: -float(r.get("score") or 0)), limit)
    return {"generated_at": utc_now_iso(), "summary": summarize(rows), "issues": rows}


def layer_coverage_gaps(*, area: str = "", search: str = "", limit: int = 500) -> dict:
    payload = build_sector_coverage_payload()
    sectors = payload.get("sectors") or []
    lte_bands = payload.get("lte_tech_bands") or []
    issues: list[dict] = []
    for sec in sectors:
        if area and area.lower() != "all" and str(sec.get("area") or "").lower() != area.lower():
            continue
        if search:
            q = search.lower()
            if q not in str(sec.get("site_id") or "").lower() and q not in str(sec.get("site_name") or "").lower():
                continue
        missing: list[str] = []
        if not sec.get("has_lte"):
            missing.append("LTE")
        if not sec.get("has_3g"):
            missing.append("3G")
        for band, has_layer in (sec.get("lte_coverage") or {}).items():
            if not has_layer and band in lte_bands:
                missing.append(band)
        if not missing:
            continue
        score = bounded_score(35 if "LTE" in missing else 0, 20 if "3G" in missing else 0, min(35, len(missing) * 7))
        issues.append(issue(
            module="Layer Coverage",
            category="Coverage",
            title=f"Missing layer at site {sec.get('site_id')} sector {sec.get('sector')}",
            summary=f"Inventory-based missing layers: {', '.join(missing[:8])}.",
            score=score,
            site_id=str(sec.get("site_id") or ""),
            area=str(sec.get("area") or ""),
            vendor=", ".join(sec.get("vendors") or []),
            technology="Inventory",
            evidence={"missing_layers": missing, "available_layers": sec.get("tech_bands") or []},
            recommendation="Validate planned layer design, cell status, and metadata completeness for this sector.",
            source_url="/layer-coverage",
        ))
    rows = _limit(sorted(issues, key=lambda r: -float(r.get("score") or 0)), limit)
    return {"generated_at": payload.get("generated_at") or utc_now_iso(), "summary": summarize(rows), "issues": rows}


def overshooting_candidates(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 200) -> dict:
    lines = neighbor.load_neighbor_lines(vendor, technology, min_attempts=5, max_lines=max(800, limit * 5))
    cell_meta = metadata.cell_index()
    issues: list[dict] = []
    for row in lines:
        distance = to_float(row.get("distance_km"))
        if distance is None or distance < 8:
            continue
        src = str(row.get("source_cell") or "")
        meta = cell_meta.get(src.lower(), {})
        if area and area.lower() != "all" and str(meta.get("area") or "").lower() != area.lower():
            continue
        failures = to_float(row.get("ho_failures")) or 0
        attempts = to_float(row.get("ho_attempts")) or 0
        sr = to_float(row.get("ho_success_rate"))
        score = bounded_score(min(45, (distance - 8) * 4), min(25, failures / max(1, attempts) * 100), max(0, 95 - sr) if sr is not None else 8)
        if score < 30:
            continue
        issues.append(issue(
            module="Overshooting Detector",
            category="Coverage",
            title=f"Possible overshooting from {src}",
            summary=f"Far neighbor {row.get('target_cell')} at {distance:.1f} km with {attempts:.0f} HO attempts.",
            score=score,
            cells=[src, str(row.get("target_cell") or "")],
            site_id=str(row.get("source_site_id") or meta.get("site_id") or ""),
            area=str(meta.get("area") or ""),
            vendor=str(row.get("vendor") or meta.get("vendor") or ""),
            technology=str(row.get("technology") or meta.get("technology") or ""),
            evidence={"distance_km": distance, "attempts": attempts, "failures": failures, "success_rate": sr, "source_azimuth": row.get("source_azimuth")},
            recommendation="Review antenna tilt/azimuth, power, neighbor design, and TA/MR evidence if available.",
            source_url="/overshooting-detector",
        ))
    rows = _limit(sorted(issues, key=lambda r: -float(r.get("score") or 0)), limit)
    return {"generated_at": utc_now_iso(), "summary": summarize(rows), "issues": rows, "note": "Heuristic: no TA/MR/RSRP source is required for this first pass."}


def neighbor_quality(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 200) -> dict:
    rows = neighbor.build_quality_issues(vendor, technology, limit=limit)
    rows = filter_rows(rows, area=area)
    return {"generated_at": utc_now_iso(), "summary": summarize(rows), "issues": _limit(rows, limit)}


def cm_parameter_audit(*, vendor: str = "all", technology: str = "all", limit: int = 500) -> dict:
    rows = cm_store.latest_snapshot_rows(limit=10000)
    rules = cm_store.list_rules()
    issues: list[dict] = []
    for snap in rows:
        if vendor and vendor.lower() != "all" and str(snap.get("vendor") or "").lower() != vendor.lower():
            continue
        if technology and technology.lower() != "all" and technology.lower() not in str(snap.get("technology") or "").lower():
            continue
        param = str(snap.get("parameter") or "").lower()
        for rule in rules:
            if rule.get("vendor") and str(rule.get("vendor")).lower() != str(snap.get("vendor") or "").lower():
                continue
            if rule.get("technology") and str(rule.get("technology")).lower() not in str(snap.get("technology") or "").lower():
                continue
            if rule.get("mo_class") and str(rule.get("mo_class")).lower() != str(snap.get("mo_class") or "").lower():
                continue
            if str(rule.get("parameter") or "").lower() != param:
                continue
            value = snap.get("value")
            failed = False
            if rule.get("rule_type") == "not_empty":
                failed = not str(value or "").strip()
            elif rule.get("rule_type") == "equals":
                failed = str(value) != str(rule.get("expected_value"))
            elif rule.get("rule_type") == "range":
                val = to_float(value)
                failed = val is None or val < float(rule.get("min_value")) or val > float(rule.get("max_value"))
            if not failed:
                continue
            sev_score = {"Critical": 90, "High": 75, "Medium": 55, "Low": 30}.get(str(rule.get("severity") or "Medium"), 55)
            issues.append(issue(
                module="CM Parameter Audit",
                category="Configuration",
                title=f"{snap.get('parameter')} audit failed",
                summary=str(rule.get("description") or "Parameter is outside the rule definition."),
                score=sev_score,
                cells=[str(snap.get("cell_name") or "")] if snap.get("cell_name") else [],
                site_id=str(snap.get("site_id") or ""),
                vendor=str(snap.get("vendor") or ""),
                technology=str(snap.get("technology") or ""),
                evidence={"dn": snap.get("dn"), "mo_class": snap.get("mo_class"), "value": value, "rule": rule},
                recommendation="Review the parameter against the approved golden configuration before making any change.",
                source_url="/cm-parameter-audit",
            ))
    rows_out = _limit(sorted(issues, key=lambda r: -float(r.get("score") or 0)), limit)
    return {"generated_at": utc_now_iso(), "store": cm_store.store_stats(), "summary": summarize(rows_out), "issues": rows_out}


def change_impact(*, vendor: str = "all", technology: str = "all", limit: int = 200) -> dict:
    changes = cm_store.detect_changes(limit=limit * 2)
    degraded = {str(r.get("cell_name") or "").lower(): r for r in pm.degraded_cells(vendor="all", technology="4G", limit=500)}
    issues: list[dict] = []
    for ch in changes:
        if vendor and vendor.lower() != "all" and str(ch.get("vendor") or "").lower() != vendor.lower():
            continue
        if technology and technology.lower() != "all" and technology.lower() not in str(ch.get("technology") or "").lower():
            continue
        cell = str(ch.get("cell_name") or "")
        pm_row = degraded.get(cell.lower())
        score = 65 if pm_row else 35
        summary = f"{ch.get('parameter')} changed from {ch.get('old_value')} to {ch.get('new_value')}."
        if pm_row:
            summary += f" PM degradation also seen in {pm_row.get('category')} ({pm_row.get('change_pct')}%)."
        issues.append(issue(
            module="Change Impact",
            category="Configuration Impact",
            title=f"Change impact candidate: {ch.get('parameter')}",
            summary=summary,
            score=score,
            cells=[cell] if cell else [],
            site_id=str(ch.get("site_id") or ""),
            vendor=str(ch.get("vendor") or ""),
            technology=str(ch.get("technology") or ""),
            evidence={"change": ch, "pm_degradation": pm_row},
            recommendation="Compare PM before/after windows and check overlapping changes before attributing impact.",
            source_url="/change-impact",
        ))
    rows = _limit(sorted(issues, key=lambda r: -float(r.get("score") or 0)), limit)
    return {"generated_at": utc_now_iso(), "store": cm_store.store_stats(), "summary": summarize(rows), "issues": rows}


def rf_optimization(*, area: str = "", vendor: str = "all", technology: str = "all", limit: int = 250) -> dict:
    sections = [
        neighbor_quality(vendor=vendor, technology=technology, area=area, limit=80),
        capacity_hotspots(vendor=vendor, technology=technology, area=area, limit=80),
        overshooting_candidates(vendor=vendor, technology=technology, area=area, limit=80),
        cm_parameter_audit(vendor=vendor, technology=technology, limit=80),
        change_impact(vendor=vendor, technology=technology, limit=80),
    ]
    rows: list[dict] = []
    for section in sections:
        rows.extend(section.get("issues") or [])
    rows = filter_rows(rows, area=area, vendor=vendor, technology=technology)
    rows = _limit(rows, limit)
    return {"generated_at": utc_now_iso(), "summary": summarize(rows), "issues": rows}


def radio_morning_report(*, area: str = "", vendor: str = "all", technology: str = "all", limit: int = 100) -> dict:
    capacity = capacity_hotspots(vendor=vendor, technology=technology, area=area, limit=limit)
    neighbors = neighbor_quality(vendor=vendor, technology=technology, area=area, limit=limit)
    layers = layer_coverage_gaps(area=area, limit=limit)
    overshoot = overshooting_candidates(vendor=vendor, technology=technology, area=area, limit=limit)
    cm_audit = cm_parameter_audit(vendor=vendor, technology=technology, limit=limit)
    impact = change_impact(vendor=vendor, technology=technology, limit=limit)
    all_rows = []
    for section in (capacity, neighbors, layers, overshoot, cm_audit, impact):
        all_rows.extend(section.get("issues") or [])
    all_rows = filter_rows(all_rows, area=area, vendor=vendor, technology=technology)
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(all_rows),
        "sections": {
            "capacity_hotspots": capacity.get("issues", [])[:limit],
            "neighbor_quality": neighbors.get("issues", [])[:limit],
            "layer_coverage": layers.get("issues", [])[:limit],
            "overshooting": overshoot.get("issues", [])[:limit],
            "cm_audit": cm_audit.get("issues", [])[:limit],
            "change_impact": impact.get("issues", [])[:limit],
        },
        "issues": all_rows[:limit],
        "cm_store": cm_store.store_stats(),
    }

