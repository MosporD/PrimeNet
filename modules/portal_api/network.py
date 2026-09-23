"""Build network-footprint payloads for NexPulse (and future portals)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def technology_footprint(*, area: str | None = None, limit_cells: int = 200_000) -> dict:
    """Active cell/site counts by RAT from metadata inventory."""
    from core.radio import metadata

    index = metadata.cell_index()
    tech_cells: Counter[str] = Counter()
    tech_sites: dict[str, set[str]] = {}
    area_filter = (area or "").strip().lower()
    scanned = 0
    for _key, meta in index.items():
        scanned += 1
        if scanned > limit_cells:
            break
        if area_filter and area_filter != "all":
            if str(meta.get("area") or "").strip().lower() != area_filter:
                continue
        tech = str(meta.get("technology") or "unknown").strip() or "unknown"
        tech_cells[tech] += 1
        site = str(meta.get("site_id") or "").strip()
        if site:
            tech_sites.setdefault(tech, set()).add(site)

    by_tech = [
        {
            "technology": tech,
            "cell_count": count,
            "site_count": len(tech_sites.get(tech, ())),
        }
        for tech, count in sorted(tech_cells.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "as_of": _utc_now(),
        "area": area or "all",
        "technologies": by_tech,
        "totals": {
            "cells": sum(tech_cells.values()),
            "sites": len({s for sites in tech_sites.values() for s in sites}),
        },
        "source": "primenet.metadata",
    }


def congested_sites(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 100) -> dict:
    """Capacity-pressure cells/sites from the Capacity Hotspots detector."""
    from core.radio.insights import capacity_hotspots

    payload = capacity_hotspots(
        vendor=vendor or "all",
        technology=technology or "all",
        area=area or "",
        limit=max(1, min(500, int(limit or 100))),
    )
    issues = payload.get("issues") or []
    sites: dict[str, dict] = {}
    for row in issues:
        site_id = str(row.get("site_id") or "").strip() or str(row.get("cells") or [""])[0]
        if not site_id:
            continue
        prev = sites.get(site_id)
        score = float(row.get("score") or 0)
        if prev is None or score > float(prev.get("score") or 0):
            sites[site_id] = {
                "site_id": site_id,
                "area": row.get("area") or "",
                "vendor": row.get("vendor") or "",
                "technology": row.get("technology") or "",
                "score": score,
                "title": row.get("title") or "",
                "cells": row.get("cells") or [],
            }
    ranked = sorted(sites.values(), key=lambda r: -float(r.get("score") or 0))
    return {
        "as_of": payload.get("generated_at") or _utc_now(),
        "summary": payload.get("summary") or {},
        "site_count": len(ranked),
        "sites": ranked[: max(1, min(200, int(limit or 100)))],
        "source": "primenet.capacity_hotspots",
    }


def serviceability(*, area: str = "", limit: int = 200) -> dict:
    """Layer-coverage gaps (missing LTE/3G/5G on sectors) as a serviceability signal."""
    from core.radio.insights import layer_coverage_gaps

    payload = layer_coverage_gaps(area=area or "", search="", limit=max(1, min(1000, int(limit or 200))))
    issues = payload.get("issues") or []
    missing_counts: Counter[str] = Counter()
    for row in issues:
        evidence = row.get("evidence") or {}
        for layer in evidence.get("missing_layers") or evidence.get("missing") or []:
            missing_counts[str(layer)] += 1
        # Fallback: parse title/summary if evidence shape differs
        if not evidence.get("missing"):
            for token in ("LTE", "3G", "5G", "NR"):
                summary = str(row.get("summary") or "")
                if token in summary and "missing" in summary.lower():
                    missing_counts[token] += 1
    return {
        "as_of": payload.get("generated_at") or _utc_now(),
        "summary": payload.get("summary") or {},
        "gap_count": len(issues),
        "missing_layers": [
            {"layer": layer, "sector_count": count}
            for layer, count in sorted(missing_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "issues": [
            {
                "site_id": r.get("site_id"),
                "area": r.get("area"),
                "title": r.get("title"),
                "score": r.get("score"),
                "cells": r.get("cells"),
            }
            for r in issues[:50]
        ],
        "source": "primenet.layer_coverage",
    }


def footprint_bundle(*, area: str | None = None, congested_limit: int = 50) -> dict:
    """Single round-trip payload for NexPulse provider warm-up / overview."""
    return {
        "as_of": _utc_now(),
        "technology_footprint": technology_footprint(area=area),
        "congested": congested_sites(area=area or "", limit=congested_limit),
        "serviceability": serviceability(area=area or "", limit=200),
    }
