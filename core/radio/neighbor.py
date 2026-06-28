"""Neighbor quality helpers built on raw neighbor export linking."""

from __future__ import annotations

import math
import os
import sqlite3

from modules.network_map.neighbor_raw_linking import build_raw_neighbor_lines
from modules.network_map.routes import (
    _resolve_huawei_neighbor_export_table,
    _resolve_raw_neighbor_table_for_vendor,
)
from sync_config import HUAWEI_NEIGHBOR_RAW_DB, NEIGHBOR_KPI_DB

from .scoring import bounded_score, issue


TECHNOLOGIES = ["2G-2G", "3G-3G", "4G-4G Intra-eNB", "4G-4G Inter-eNB"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _load_vendor_lines(vendor: str, technology: str, *, min_attempts: float, max_lines: int) -> list[dict]:
    db_path = HUAWEI_NEIGHBOR_RAW_DB if vendor == "huawei" else NEIGHBOR_KPI_DB
    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if vendor == "huawei":
            table = _resolve_huawei_neighbor_export_table(conn, technology)
        else:
            table = _resolve_raw_neighbor_table_for_vendor(conn, technology, vendor)
        if not table:
            return []
        lines, _skipped, _candidates, _period, _msg = build_raw_neighbor_lines(
            neighbor_conn=conn,
            raw_table=table,
            technology=technology,
            vendor=vendor,
            cell_norm="",
            site_id_filter="",
            min_attempts=min_attempts,
            max_lines=max_lines,
            max_scan_rows=max(max_lines * 50, 8000),
        )
        return lines
    finally:
        conn.close()


def load_neighbor_lines(vendor: str = "all", technology: str = "all", *, min_attempts: float = 10, max_lines: int = 1200) -> list[dict]:
    vendors = ["nokia", "huawei"] if vendor in ("", "all", None) else [vendor.lower()]
    techs = TECHNOLOGIES if technology in ("", "all", None) else [technology]
    out: list[dict] = []
    per_slice = max(50, max_lines // max(1, len(vendors) * len(techs)))
    for v in vendors:
        for tech in techs:
            out.extend(_load_vendor_lines(v, tech, min_attempts=min_attempts, max_lines=per_slice))
    for row in out:
        try:
            row["distance_km"] = round(haversine_km(
                float(row["source_lat"]),
                float(row["source_lng"]),
                float(row["target_lat"]),
                float(row["target_lng"]),
            ), 2)
        except Exception:
            row["distance_km"] = None
    return out[:max_lines]


def build_quality_issues(vendor: str = "all", technology: str = "all", *, min_attempts: float = 10, limit: int = 200) -> list[dict]:
    lines = load_neighbor_lines(vendor, technology, min_attempts=min_attempts, max_lines=max(limit * 4, 400))
    pair_set = {
        (str(r.get("source_cell") or "").lower(), str(r.get("target_cell") or "").lower())
        for r in lines
    }
    issues: list[dict] = []
    for row in lines:
        attempts = float(row.get("ho_attempts") or 0)
        sr = row.get("ho_success_rate")
        failures = row.get("ho_failures")
        distance = row.get("distance_km")
        missing_recip = (
            str(row.get("target_cell") or "").lower(),
            str(row.get("source_cell") or "").lower(),
        ) not in pair_set
        sr_penalty = max(0.0, 95.0 - float(sr)) * 1.4 if sr is not None else 10.0
        failure_penalty = min(35.0, float(failures or 0) / max(1.0, attempts) * 100.0) if failures is not None else 0.0
        distance_penalty = 20.0 if distance is not None and float(distance) >= 12 else 0.0
        recip_penalty = 15.0 if missing_recip else 0.0
        cross_vendor_penalty = 8.0 if row.get("target_vendor") and row.get("target_vendor") != row.get("vendor") else 0.0
        score = bounded_score(sr_penalty, failure_penalty, distance_penalty, recip_penalty, cross_vendor_penalty)
        if score < 25:
            continue
        labels = []
        if sr is not None and float(sr) < 95:
            labels.append(f"HO SR {float(sr):.1f}%")
        if failures is not None:
            labels.append(f"{float(failures):.0f} failed HOs")
        if missing_recip:
            labels.append("missing reciprocal")
        if distance is not None and float(distance) >= 12:
            labels.append(f"{float(distance):.1f} km")
        summary = ", ".join(labels) or "Neighbor relation needs review"
        issues.append(issue(
            module="Neighbor Quality",
            category="Mobility",
            title=f"{row.get('source_cell')} -> {row.get('target_cell')}",
            summary=summary,
            score=score,
            cells=[str(row.get("source_cell") or ""), str(row.get("target_cell") or "")],
            site_id=str(row.get("source_site_id") or ""),
            vendor=str(row.get("vendor") or ""),
            technology=str(row.get("technology") or ""),
            evidence={
                "attempts": attempts,
                "success_rate": sr,
                "failures": failures,
                "distance_km": distance,
                "missing_reciprocal": missing_recip,
                "target_vendor": row.get("target_vendor"),
            },
            recommendation="Check neighbor definition, reciprocity, distance, and handover thresholds.",
            source_url="/neighbor-quality",
        ))
    return sorted(issues, key=lambda r: -float(r.get("score") or 0))[:limit]

