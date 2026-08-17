"""Relation-level HO workbook and vendor/IRAT border view."""

from __future__ import annotations

from . import metadata, neighbor
from .scoring import bounded_score, filter_rows, issue, summarize, to_float, utc_now_iso


def _rat_family(text: str) -> str:
    t = str(text or "").upper()
    if "5G" in t or "NR" in t:
        return "5G"
    if "4G" in t or "LTE" in t:
        return "4G"
    if "3G" in t or "WCDMA" in t or "UMTS" in t:
        return "3G"
    if "2G" in t or "GSM" in t:
        return "2G"
    return t.strip() or ""


def mobility_explorer(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 250) -> dict:
    """Relation performance workbook — not a map and not a scored issue-only list."""
    lines = neighbor.load_neighbor_lines(vendor, technology, min_attempts=5, max_lines=max(limit * 6, 800))
    cell_meta = metadata.cell_index()
    pair_set = {
        (str(r.get("source_cell") or "").lower(), str(r.get("target_cell") or "").lower())
        for r in lines
    }
    issues: list[dict] = []
    for row in lines:
        src = str(row.get("source_cell") or "")
        tgt = str(row.get("target_cell") or "")
        meta = cell_meta.get(src.lower(), {})
        if area and area.lower() != "all" and str(meta.get("area") or "").lower() != area.lower():
            continue
        attempts = to_float(row.get("ho_attempts")) or 0
        sr = to_float(row.get("ho_success_rate"))
        failures = to_float(row.get("ho_failures"))
        distance = to_float(row.get("distance_km"))
        missing_recip = (tgt.lower(), src.lower()) not in pair_set
        sr_pen = max(0.0, 97.0 - sr) * 1.2 if sr is not None else 6.0
        fail_pen = min(30.0, (failures or 0) / max(1.0, attempts) * 100) if failures is not None else 0.0
        recip_pen = 18.0 if missing_recip else 0.0
        score = bounded_score(sr_pen, fail_pen, recip_pen, min(15.0, attempts / 200.0))
        labels = []
        if sr is not None:
            labels.append(f"HO SR {sr:.1f}%")
        labels.append(f"{attempts:.0f} attempts")
        if missing_recip:
            labels.append("one-way")
        if distance is not None:
            labels.append(f"{distance:.1f} km")
        issues.append(issue(
            module="Mobility Explorer",
            category="Handover relation",
            title=f"{src} → {tgt}",
            summary=", ".join(labels),
            score=max(score, 15.0),
            cells=[src, tgt],
            site_id=str(row.get("source_site_id") or meta.get("site_id") or ""),
            area=str(meta.get("area") or ""),
            vendor=str(row.get("vendor") or meta.get("vendor") or ""),
            technology=str(row.get("technology") or meta.get("technology") or ""),
            evidence={
                "attempts": attempts,
                "success_rate": sr,
                "failures": failures,
                "distance_km": distance,
                "source_azimuth": row.get("source_azimuth"),
                "target_azimuth": row.get("target_azimuth"),
                "one_way": missing_recip,
                "target_vendor": row.get("target_vendor"),
                "ta_mr_available": False,
            },
            recommendation="Review neighbor definition, HO thresholds, and whether the reverse relation exists.",
            source_url="/mobility-explorer",
        ))
    issues.sort(key=lambda r: (-float(r.get("score") or 0), -float((r.get("evidence") or {}).get("attempts") or 0)))
    rows = filter_rows(issues[: max(1, int(limit))], area=area, vendor=vendor, technology=technology)
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(rows),
        "issues": rows,
        "freshness": neighbor.neighbor_freshness(),
        "note": "Workbook of neighbor HO performance. Map is geospatial; Neighbor Quality is a scored subset.",
    }


def irat_border(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 200) -> dict:
    lines = neighbor.load_neighbor_lines("all", "all" if technology in ("", "all", None) else technology, min_attempts=3, max_lines=max(limit * 8, 1200))
    cell_meta = metadata.cell_index()
    issues: list[dict] = []
    for row in lines:
        src = str(row.get("source_cell") or "")
        tgt = str(row.get("target_cell") or "")
        src_meta = cell_meta.get(src.lower(), {})
        tgt_meta = cell_meta.get(tgt.lower(), {})
        if area and area.lower() != "all" and str(src_meta.get("area") or "").lower() != area.lower():
            continue
        src_vendor = str(row.get("vendor") or src_meta.get("vendor") or "").strip()
        tgt_vendor = str(row.get("target_vendor") or tgt_meta.get("vendor") or "").strip()
        src_rat = _rat_family(src_meta.get("technology") or row.get("technology"))
        tgt_rat = _rat_family(tgt_meta.get("technology") or "")
        vendor_border = bool(src_vendor and tgt_vendor and src_vendor.lower() != tgt_vendor.lower())
        rat_border = bool(src_rat and tgt_rat and src_rat != tgt_rat)
        if not vendor_border and not rat_border:
            continue
        if vendor not in ("", "all", None) and src_vendor.lower() != vendor.lower() and tgt_vendor.lower() != vendor.lower():
            continue
        sr = to_float(row.get("ho_success_rate"))
        attempts = to_float(row.get("ho_attempts")) or 0
        score = bounded_score(
            25 if vendor_border else 0,
            20 if rat_border else 0,
            max(0.0, 96.0 - sr) if sr is not None else 8.0,
            min(20.0, attempts / 150.0),
        )
        kind = []
        if vendor_border:
            kind.append(f"{src_vendor}↔{tgt_vendor}")
        if rat_border:
            kind.append(f"{src_rat}↔{tgt_rat}")
        issues.append(issue(
            module="IRAT / Vendor Border",
            category="Border mobility",
            title=f"{src} → {tgt}",
            summary=f"{' / '.join(kind)}; HO SR {sr:.1f}%" if sr is not None else " / ".join(kind),
            score=score,
            cells=[src, tgt],
            site_id=str(row.get("source_site_id") or src_meta.get("site_id") or ""),
            area=str(src_meta.get("area") or ""),
            vendor=src_vendor,
            technology=f"{src_rat}-{tgt_rat}" if rat_border else str(row.get("technology") or src_rat),
            evidence={
                "source_vendor": src_vendor,
                "target_vendor": tgt_vendor,
                "source_rat": src_rat,
                "target_rat": tgt_rat,
                "attempts": attempts,
                "success_rate": sr,
                "distance_km": row.get("distance_km"),
                "source_azimuth": row.get("source_azimuth"),
            },
            recommendation="Check IRAT/vendor-border neighbor plan, HO allowed lists, and overlapping coverage on the Zain overlay.",
            source_url="/irat-border",
        ))
    issues.sort(key=lambda r: -float(r.get("score") or 0))
    rows = issues[: max(1, int(limit))]
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(rows),
        "issues": rows,
        "freshness": neighbor.neighbor_freshness(),
        "note": "Nokia↔Huawei and inter-RAT relations on the live overlay. Intra-vendor same-RAT neighbors stay in Mobility Explorer.",
    }
