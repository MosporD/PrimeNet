"""Weak labels from existing radio detectors (Phase 2)."""

from __future__ import annotations

from . import config as cfg


def _cell_set(issues: list[dict]) -> set[str]:
    out: set[str] = set()
    for row in issues or []:
        for cell in row.get("cells") or []:
            name = str(cell or "").strip().lower()
            if name:
                out.add(name)
        name = str(row.get("cell_name") or "").strip().lower()
        if name:
            out.add(name)
    return out


def collect_weak_labels(vendor: str, technology: str = cfg.TECHNOLOGY) -> dict[str, dict[str, float]]:
    """Return cell_lower -> {cause: 0/1} using current detectors. Failures are skipped."""
    labels: dict[str, dict[str, float]] = {}

    def _mark(cells: set[str], cause: str) -> None:
        for cell in cells:
            bucket = labels.setdefault(cell, {k: 0.0 for k in cfg.CAUSE_LABELS})
            bucket[cause] = 1.0

    try:
        from modules.sleeping_cells.logic import detect_sleeping_cells

        payload = detect_sleeping_cells(vendor=vendor, technology=technology, limit=400)
        _mark(_cell_set(payload.get("issues") or []), "sleeping")
    except Exception:
        pass

    try:
        from core.radio.insights import capacity_hotspots, change_impact, neighbor_quality

        _mark(_cell_set(capacity_hotspots(vendor=vendor, technology=technology, limit=300).get("issues") or []), "congestion")
        _mark(_cell_set(change_impact(vendor=vendor, technology=technology, limit=300).get("issues") or []), "cm_change")
        _mark(_cell_set(neighbor_quality(vendor=vendor, technology="4G-4G", limit=300).get("issues") or []), "neighbor")
    except Exception:
        pass

    return labels


def heuristic_cause_probs(row: dict) -> dict[str, float]:
    """Soft scores from z-features when a classifier is not trained."""
    z = row.get("z") or {}
    raw = {
        "sleeping": 0.15 if float(z.get("Utilization") or 0) < -1.5 else 0.02,
        "congestion": max(0.0, float(z.get("Utilization") or 0)),
        "interference": max(0.0, float(z.get("Interference") or 0)),
        "mobility": max(0.0, float(z.get("Mobility") or 0)),
        "cm_change": 0.05,
        "neighbor": max(0.0, float(row.get("nbr_missing_recip") or 0) * 2.0)
        + (0.4 if float(row.get("nbr_ho_sr") or 100) < 95 else 0.0),
    }
    total = sum(raw.values()) or 1.0
    return {k: round(v / total, 4) for k, v in raw.items()}
