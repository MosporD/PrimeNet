"""Phase 3a — neighbor-graph aggregates attached to cell-day rows."""

from __future__ import annotations

from collections import defaultdict

from core.radio.neighbor import load_neighbor_lines

from . import config as cfg


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def neighbor_stats(vendor: str, technology: str = "4G-4G") -> dict[str, dict[str, float]]:
    lines = load_neighbor_lines(
        vendor=vendor,
        technology=technology,
        min_attempts=cfg.NEIGHBOR_MIN_ATTEMPTS,
        max_lines=cfg.NEIGHBOR_MAX_LINES,
    )
    pair_set = {
        (str(r.get("source_cell") or "").strip().lower(), str(r.get("target_cell") or "").strip().lower())
        for r in lines
    }
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in lines:
        src = str(row.get("source_cell") or "").strip()
        if src:
            buckets[src.lower()].append(row)

    out: dict[str, dict[str, float]] = {}
    for key, items in buckets.items():
        n = len(items)
        attempts = [_f(r.get("ho_attempts")) for r in items]
        srs = [s for s in (_f(r.get("ho_success_rate"), default=float("nan")) for r in items) if s == s]
        dists = [d for d in (_f(r.get("distance_km"), default=float("nan")) for r in items) if d == d]
        missing = 0.0
        for r in items:
            tgt = str(r.get("target_cell") or "").strip().lower()
            src = str(r.get("source_cell") or "").strip().lower()
            if tgt and (tgt, src) not in pair_set:
                missing += 1.0
        name = str(items[0].get("source_cell") or key)
        out[name.lower()] = {
            "nbr_count": float(n),
            "nbr_ho_attempts": sum(attempts) / n if n else 0.0,
            "nbr_ho_sr": sum(srs) / len(srs) if srs else 0.0,
            "nbr_distance_km": sum(dists) / len(dists) if dists else 0.0,
            "nbr_missing_recip": missing / n if n else 0.0,
        }
        out[key] = out[name.lower()]
    return out


def neighbor_adjacency(vendor: str, technology: str = "4G-4G") -> dict[str, list[str]]:
    lines = load_neighbor_lines(
        vendor=vendor,
        technology=technology,
        min_attempts=cfg.NEIGHBOR_MIN_ATTEMPTS,
        max_lines=cfg.NEIGHBOR_MAX_LINES,
    )
    adj: dict[str, list[str]] = defaultdict(list)
    for row in lines:
        src = str(row.get("source_cell") or "").strip().lower()
        tgt = str(row.get("target_cell") or "").strip().lower()
        if src and tgt:
            adj[src].append(tgt)
    return dict(adj)


def attach_neighbor_features(rows: list[dict], vendor: str) -> None:
    stats = neighbor_stats(vendor)
    for row in rows:
        key = str(row.get("cell_name") or "").strip().lower()
        info = stats.get(key) or {}
        row["nbr_count"] = info.get("nbr_count", 0.0)
        row["nbr_ho_attempts"] = info.get("nbr_ho_attempts", 0.0)
        row["nbr_ho_sr"] = info.get("nbr_ho_sr", 0.0)
        row["nbr_distance_km"] = info.get("nbr_distance_km", 0.0)
        row["nbr_missing_recip"] = info.get("nbr_missing_recip", 0.0)
