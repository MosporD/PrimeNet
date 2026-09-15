"""PM-derived Impact Score for case triage (not subscriber CEM)."""

from __future__ import annotations

from typing import Any

from core.radio.scoring import severity_from_score


SEVERITY_WEIGHT = {
    "Critical": 1.0,
    "High": 0.75,
    "Medium": 0.45,
    "Low": 0.2,
    "Info": 0.1,
}


def compute_impact_score(
    *,
    severity: str = "Medium",
    score: float = 0,
    cells: list | None = None,
    evidence: dict | None = None,
    facts: list[dict] | None = None,
    traffic_proxy: float | None = None,
) -> dict[str, Any]:
    """
    impact ≈ severity_weight * score_norm * cell_factor * traffic_factor * duration_factor

    Label in UI: Impact Score (PM)
    """
    sev = str(severity or severity_from_score(float(score or 0)))
    sev_w = SEVERITY_WEIGHT.get(sev, 0.45)
    score_norm = min(1.0, max(0.0, float(score or 0) / 100.0))
    n_cells = max(1, len(cells or []))
    cell_factor = min(1.5, 0.7 + 0.1 * n_cells)

    # Duration / magnitude from PM facts
    duration_factor = 1.0
    mag = 0.0
    for f in facts or []:
        if f.get("type") != "pm_degradation":
            continue
        try:
            mag = max(mag, abs(float(f.get("change_pct") or 0)))
        except (TypeError, ValueError):
            pass
    if mag >= 20:
        duration_factor = 1.35
    elif mag >= 10:
        duration_factor = 1.15
    elif mag >= 5:
        duration_factor = 1.05

    # Traffic proxy: explicit or from evidence counters if present
    traffic = traffic_proxy
    if traffic is None and evidence:
        for key in ("traffic", "dl_traffic", "active_users", "rrc_users"):
            if evidence.get(key) is not None:
                try:
                    traffic = float(evidence[key])
                    break
                except (TypeError, ValueError):
                    pass
    if traffic is None:
        traffic_factor = 1.0
    else:
        # log-ish scale: 0 users → 0.6, busy → up to 1.4
        traffic_factor = min(1.4, 0.6 + (float(traffic) / (float(traffic) + 50.0)))

    raw = 100.0 * sev_w * (0.4 + 0.6 * score_norm) * cell_factor * duration_factor * traffic_factor
    impact = round(min(100.0, raw), 2)
    return {
        "impact_score": impact,
        "label": "Impact Score (PM)",
        "components": {
            "severity": sev,
            "severity_weight": sev_w,
            "score_norm": round(score_norm, 3),
            "cell_count": n_cells,
            "cell_factor": round(cell_factor, 3),
            "duration_factor": round(duration_factor, 3),
            "traffic_factor": round(traffic_factor, 3),
            "change_pct_mag": mag,
        },
    }
