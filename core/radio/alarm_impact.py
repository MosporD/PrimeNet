"""Alarm bursts vs PM collapse vs CM-active/locked state."""

from __future__ import annotations

from modules.sleeping_cells.logic import detect_sleeping_cells

from . import alarm_join, metadata, pm
from .scoring import bounded_score, filter_rows, issue, summarize, utc_now_iso


def alarm_impact(*, vendor: str = "all", technology: str = "all", area: str = "", limit: int = 200) -> dict:
    sleeping = detect_sleeping_cells(vendor=vendor, technology=technology, limit=max(limit, 80))
    sleep_rows = sleeping.get("issues") or []
    alarm_payload = alarm_join.fetch_recent_alarms(limit=300)
    alarms = alarm_payload.get("alarms") or []
    cell_meta = metadata.cell_index()

    sleep_cells = []
    sleep_sites = []
    for row in sleep_rows:
        sleep_cells.extend(row.get("cells") or [])
        if row.get("site_id"):
            sleep_sites.append(str(row["site_id"]))
    matched = alarm_join.match_alarms_for_cells(sleep_cells, sleep_sites)

    issues: list[dict] = []
    for row in sleep_rows:
        cells = [str(c) for c in (row.get("cells") or []) if c]
        site = str(row.get("site_id") or "")
        keys = [c.lower() for c in cells] + ([site.lower()] if site else [])
        hits = []
        for key in keys:
            hits.extend(matched.get(key) or [])
        alarmed = bool(hits)
        names = sorted({str(a.get("alarm_name") or a.get("probable_cause") or "").strip() for a in hits if a})
        names = [n for n in names if n][:4]
        if alarmed:
            title = f"Alarmed outage candidate: {cells[0] if cells else site}"
            summary = (
                f"CM-active cell looks sleeping in PM and has live FM: {', '.join(names) or 'alarm present'}."
            )
            score = bounded_score(float(row.get("score") or 50), 25)
            category = "Alarmed vs sleeping"
            rec = "Treat as an alarmed outage first — clear/ack on OSS before a sleeping-cell reset."
        else:
            title = f"Silent sleeping cell: {cells[0] if cells else site}"
            summary = (
                "CM-active and traffic collapsed, with no matching live alarm in the current FM window. "
                "Could be barred, silent HW, or FM not configured."
            )
            score = bounded_score(float(row.get("score") or 50), 8)
            category = "Silent sleeping"
            rec = "If FM is healthy, dispatch as a silent outage (TX/RRU/barred). If FM is down, this classification is incomplete."
        if area and area.lower() != "all" and str(row.get("area") or "").lower() != area.lower():
            continue
        issues.append(issue(
            module="Alarm–PM Correlator",
            category=category,
            title=title,
            summary=summary,
            score=score,
            cells=cells,
            site_id=site,
            area=str(row.get("area") or ""),
            vendor=str(row.get("vendor") or ""),
            technology=str(row.get("technology") or ""),
            evidence={
                "sleeping": row.get("evidence"),
                "alarm_count": len(hits),
                "alarm_names": names,
                "cm_state": (row.get("evidence") or {}).get("cm_state") or "Active",
            },
            recommendation=rec,
            source_url="/alarm-impact",
        ))

    # Alarms on cells that are not in the sleeping list — still useful if PM dropped.
    degraded = {
        str(r.get("cell_name") or "").lower(): r
        for r in pm.degraded_cells(vendor=vendor if vendor != "all" else "all", technology="4G", limit=300)
    }
    for alarm in alarms[:limit]:
        me = str(alarm.get("me_name") or alarm.get("site_id") or "").strip()
        if not me:
            continue
        meta = cell_meta.get(me.lower(), {})
        pm_row = degraded.get(me.lower())
        if not pm_row and not meta:
            continue
        if vendor not in ("", "all", None):
            v = str(meta.get("vendor") or "").lower()
            if v and v != vendor.lower():
                continue
        score = bounded_score(40, 20 if pm_row else 0)
        issues.append(issue(
            module="Alarm–PM Correlator",
            category="Alarm with PM context",
            title=f"{alarm.get('alarm_name') or 'Alarm'} on {me}",
            summary=(
                f"Live FM on {me}"
                + (f"; PM also degraded in {pm_row.get('category')} ({pm_row.get('change_pct')}%)." if pm_row else ".")
            ),
            score=score,
            cells=[me],
            site_id=str(meta.get("site_id") or me),
            area=str(meta.get("area") or ""),
            vendor=str(meta.get("vendor") or ""),
            technology=str(meta.get("technology") or ""),
            evidence={"alarm": {k: alarm.get(k) for k in ("severity", "alarm_name", "occur_time", "me_name")}, "pm": pm_row},
            recommendation="Confirm whether traffic collapsed with the alarm or the cell is still carrying load.",
            source_url="/alarm-impact",
        ))

    issues.sort(key=lambda r: -float(r.get("score") or 0))
    rows = filter_rows(issues[: max(1, int(limit))], area=area, vendor=vendor, technology=technology)
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(rows),
        "issues": rows,
        "fm": {
            "alarm_count": alarm_payload.get("count") or 0,
            "notes": alarm_payload.get("notes") or [],
            "configured": alarm_payload.get("configured"),
        },
        "sleeping_params": sleeping.get("params") or {},
        "note": (
            "Joins live FM (when configured) with sleeping-cell PM and CM-active metadata. "
            "If FM is not configured, silent vs alarmed cannot be proven."
        ),
    }
