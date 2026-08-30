"""
Sleeping-cell detection.

A "sleeping" cell is on-air per CM (activity_status = Active in metadata) but
has stopped carrying traffic: its recent daily traffic collapsed to ~zero while
its own baseline (previous days) shows it normally carries meaningful load.
Uses the same daily PM sources and traffic KPI recipes as the other radio
insight modules.
"""

from __future__ import annotations

from core.radio import metadata, pm
from core.radio.scoring import bounded_score, issue, summarize, utc_now_iso
from core.radio.section_runner import cached_build
from modules.son_analytics.pm_helpers import (
    _cell_daily_kpi_series,
    resolve_kpi_column,
    vendor_pm_sources,
)

TRAFFIC_ALIASES = list(pm.KPI_RECIPES["traffic"]["aliases"])
USERS_ALIASES = list(pm.KPI_RECIPES["users"]["aliases"])

# PM tables are per family (4G-FDD/TDD share the 4G table); metadata resolves the RAT.
PM_TECH_FAMILIES = ["2G", "3G", "4G", "5G"]

DEFAULT_RECENT_DAYS = 2
DEFAULT_BASELINE_DAYS = 7
DEFAULT_MIN_BASELINE = 1.0   # ignore cells whose normal traffic is below this (KPI units)
QUIET_RATIO = 0.02           # recent value counts as "quiet" below 2% of baseline
QUIET_ABS_FLOOR = 0.05       # ... or below this absolute floor


def _families_for(technology: str) -> list[str]:
    t = str(technology or "all").strip().upper()
    if not t or t == "ALL":
        return PM_TECH_FAMILIES
    if t.startswith("4G") or "LTE" in t:
        return ["4G"]
    return [t] if t in PM_TECH_FAMILIES else PM_TECH_FAMILIES


def _quiet_cutoff(baseline_avg: float) -> float:
    return max(QUIET_ABS_FLOOR, baseline_avg * QUIET_RATIO)


def detect_sleeping_cells(
    *,
    vendor: str = "all",
    technology: str = "all",
    limit: int = 200,
    recent_days: int = DEFAULT_RECENT_DAYS,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    min_baseline: float = DEFAULT_MIN_BASELINE,
    include_alarms: bool = True,
    force_refresh: bool = False,
) -> dict:
    recent_days = max(1, min(7, int(recent_days)))
    baseline_days = max(3, min(21, int(baseline_days)))
    min_baseline = max(0.0, float(min_baseline))

    def _copy_scan(payload: dict) -> dict:
        return {
            "issues": [dict(row) for row in (payload.get("issues") or [])],
            "scanned_cells": payload.get("scanned_cells") or 0,
        }

    scan = cached_build(
        f"sleeping.scan|{vendor}|{technology}|{recent_days}|{baseline_days}|{min_baseline}",
        lambda: _scan_sleeping_cells(
            vendor=vendor,
            technology=technology,
            recent_days=recent_days,
            baseline_days=baseline_days,
            min_baseline=min_baseline,
        ),
        force=force_refresh,
        copy=_copy_scan,
    )
    issues = list(scan.get("issues") or [])[: max(1, int(limit))]
    scanned_cells = int(scan.get("scanned_cells") or 0)

    alarm_notes: list[str] = []
    if not include_alarms:
        return {
            "generated_at": utc_now_iso(),
            "summary": summarize(issues),
            "issues": issues,
            "params": {
                "recent_days": recent_days,
                "baseline_days": baseline_days,
                "min_baseline": min_baseline,
                "scanned_active_cells": scanned_cells,
                "alarm_join": [],
            },
            "note": "CM-active + traffic collapse. Alarm join skipped for this run.",
        }

    try:
        from core.radio.alarm_join import fetch_recent_alarms, match_alarms_for_cells

        fm = fetch_recent_alarms(limit=200)
        alarm_notes = list(fm.get("notes") or [])
        hits = match_alarms_for_cells(
            [c for row in issues for c in (row.get("cells") or [])],
            [str(row.get("site_id") or "") for row in issues],
        )
        for row in issues:
            keys = [str(c).lower() for c in (row.get("cells") or [])]
            if row.get("site_id"):
                keys.append(str(row["site_id"]).lower())
            matched = []
            for key in keys:
                matched.extend(hits.get(key) or [])
            names = sorted({str(a.get("alarm_name") or "").strip() for a in matched if a})
            names = [n for n in names if n][:3]
            evidence = dict(row.get("evidence") or {})
            evidence["alarm_count"] = len(matched)
            evidence["alarm_names"] = names
            evidence["alarm_status"] = "alarmed" if matched else ("no_match" if fm.get("alarms") else "fm_unavailable")
            evidence["fm_notes"] = alarm_notes
            row["evidence"] = evidence
            if matched:
                row["summary"] = f"{row.get('summary')} Live FM: {', '.join(names) or 'alarm present'}."
                row["recommendation"] = (
                    "This CM-active quiet cell also has a live alarm — treat as an alarmed outage, "
                    "not only a sleeping-cell reset."
                )
    except Exception as exc:
        alarm_notes = [str(exc)]

    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(issues),
        "issues": issues,
        "params": {
            "recent_days": recent_days,
            "baseline_days": baseline_days,
            "min_baseline": min_baseline,
            "scanned_active_cells": scanned_cells,
            "alarm_join": alarm_notes,
        },
        "note": "CM-active + traffic collapse. Alarm names are joined from live FM when configured; otherwise the detector cannot tell sleeping vs alarmed.",
    }


def _scan_sleeping_cells(
    *,
    vendor: str,
    technology: str,
    recent_days: int,
    baseline_days: int,
    min_baseline: float,
) -> dict:
    lookback = recent_days + baseline_days + 3
    cell_meta = metadata.cell_index()  # CM-active cells only (PER_TABLE_ACTIVE_WHERE)
    issues: list[dict] = []
    scanned_cells = 0
    seen_cells: set[str] = set()

    for family in _families_for(technology):
        for vlabel, db_path, table in vendor_pm_sources(vendor, family, scope="daily"):
            kpi_col = resolve_kpi_column(db_path, table, TRAFFIC_ALIASES) or resolve_kpi_column(
                db_path, table, USERS_ALIASES
            )
            if not kpi_col:
                continue
            series_map = _cell_daily_kpi_series(db_path, table, kpi_col, lookback_days=lookback)
            for cell, series in series_map.items():
                cell_key = str(cell).strip()
                if not cell_key or cell_key.lower() in seen_cells:
                    continue
                meta = cell_meta.get(cell_key.lower())
                if not meta:
                    continue  # not on-air per CM (or unknown cell) — not "sleeping"
                meta_vendor = str(meta.get("vendor") or "").strip().lower()
                if meta_vendor and meta_vendor != vlabel.lower():
                    continue

                scanned_cells += 1
                recent = series[:recent_days]
                baseline = series[recent_days:recent_days + baseline_days]
                if len(recent) < 1 or len(baseline) < 3:
                    continue
                baseline_vals = [v for _, v in baseline]
                baseline_avg = sum(baseline_vals) / len(baseline_vals)
                if baseline_avg < min_baseline:
                    continue
                cutoff = _quiet_cutoff(baseline_avg)
                recent_max = max(v for _, v in recent)
                if recent_max > cutoff:
                    continue

                # Consecutive quiet days from the newest sample (may extend past recent_days).
                days_asleep = 0
                for _, val in series:
                    if val <= cutoff:
                        days_asleep += 1
                    else:
                        break

                seen_cells.add(cell_key.lower())
                last_day, last_val = series[0]
                score = bounded_score(
                    45,
                    min(25.0, baseline_avg ** 0.5),
                    min(30.0, days_asleep * 10.0),
                )
                issues.append(issue(
                    module="Sleeping Cells",
                    category="Availability",
                    title=f"Sleeping cell {cell_key}",
                    summary=(
                        f"CM state Active but '{kpi_col}' flatlined for {days_asleep} day(s): "
                        f"latest={round(last_val, 3)} on {last_day} vs baseline avg "
                        f"{round(baseline_avg, 2)} over previous {len(baseline_vals)} day(s)."
                    ),
                    score=score,
                    cells=[cell_key],
                    site_id=str(meta.get("site_id") or ""),
                    area=str(meta.get("area") or ""),
                    vendor=str(meta.get("vendor") or vlabel),
                    technology=str(meta.get("technology") or family),
                    evidence={
                        "kpi": kpi_col,
                        "cm_state": "Active",
                        "days_asleep": days_asleep,
                        "baseline_avg": round(baseline_avg, 3),
                        "quiet_cutoff": round(cutoff, 3),
                        "recent": [{"date": d, "value": round(v, 3)} for d, v in recent],
                        "baseline": [{"date": d, "value": round(v, 3)} for d, v in baseline],
                    },
                    recommendation=(
                        "Verify cell state on the OSS (alarms, TX path, RET/RRU, transmission). "
                        "A CM-active cell with zero traffic usually means a silent outage, "
                        "barred cell, or sleeping baseband — reset or dispatch as needed."
                    ),
                    source_url="/sleeping-cells",
                ))

    issues.sort(key=lambda r: -float(r.get("score") or 0))
    return {"issues": issues, "scanned_cells": scanned_cells}
