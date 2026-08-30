"""Common scoring helpers for radio insight modules."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any


SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(*parts: object) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            out = float(value)
            return out if math.isfinite(out) else None
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        out = float(text)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def severity_from_score(score: float) -> str:
    if score >= 85:
        return "Critical"
    if score >= 70:
        return "High"
    if score >= 45:
        return "Medium"
    if score > 0:
        return "Low"
    return "Info"


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(str(severity or ""), 99)


def bounded_score(*values: float | None) -> float:
    total = 0.0
    for value in values:
        if value is None:
            continue
        total += max(0.0, float(value))
    return round(min(100.0, total), 2)


def _default_threshold_span(direction: str, threshold_bad: float) -> float:
    """Headroom past the operator target that maps to score=100."""
    thr = abs(float(threshold_bad))
    if str(direction or "").strip().lower() == "lower_worse":
        room = 100.0 - thr if 0 <= thr <= 100 else 10.0
        return max(5.0, min(20.0, room if room > 0 else 10.0))
    if thr >= 50:
        return 20.0
    if thr <= 5:
        return 8.0
    return 15.0


def score_vs_threshold(
    value: float | None,
    *,
    direction: str = "higher_worse",
    threshold_bad: float | None = None,
    span: float | None = None,
) -> float:
    """Map a KPI versus the operator target to 0–100 (0 = at/better than target)."""
    if value is None or threshold_bad is None:
        return 0.0
    try:
        val = float(value)
        thr = float(threshold_bad)
    except (TypeError, ValueError):
        return 0.0
    direction_n = str(direction or "higher_worse").strip().lower()
    try:
        width = float(span) if span not in (None, "") else _default_threshold_span(direction_n, thr)
    except (TypeError, ValueError):
        width = _default_threshold_span(direction_n, thr)
    if width <= 0:
        width = 10.0
    excess = (thr - val) if direction_n == "lower_worse" else (val - thr)
    if excess <= 0:
        return 0.0
    return round(min(100.0, 100.0 * excess / width), 2)


def breached_threshold(
    value: float | None,
    *,
    direction: str = "higher_worse",
    threshold_bad: float | None = None,
) -> bool:
    """True when the value is worse than the operator target."""
    if value is None or threshold_bad is None:
        return False
    try:
        val = float(value)
        thr = float(threshold_bad)
    except (TypeError, ValueError):
        return False
    if str(direction or "").strip().lower() == "lower_worse":
        return val < thr
    return val > thr


def score_vs_preset(value: float | None, preset: dict | None) -> float:
    """Score a KPI using a Network Health category preset (`threshold_bad`)."""
    if not preset:
        return 0.0
    return score_vs_threshold(
        value,
        direction=str(preset.get("direction") or "higher_worse"),
        threshold_bad=preset.get("threshold_bad"),
        span=preset.get("threshold_span"),
    )


def issue(
    *,
    module: str,
    category: str,
    title: str,
    summary: str,
    score: float,
    cells: list[str] | None = None,
    site_id: str | None = None,
    area: str | None = None,
    vendor: str | None = None,
    technology: str | None = None,
    evidence: dict[str, Any] | None = None,
    recommendation: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    severity = severity_from_score(score)
    return {
        "id": stable_id(module, category, title, site_id, ",".join(cells or [])),
        "module": module,
        "category": category,
        "severity": severity,
        "score": round(float(score or 0), 2),
        "title": title,
        "summary": summary,
        "cells": cells or [],
        "site_id": site_id or "",
        "area": area or "",
        "vendor": vendor or "",
        "technology": technology or "",
        "evidence": evidence or {},
        "recommendation": recommendation or "",
        "source_url": source_url or "",
    }


def filter_rows(
    rows: list[dict],
    *,
    area: str = "",
    vendor: str = "",
    technology: str = "",
    severity: str = "",
    search: str = "",
) -> list[dict]:
    out = rows
    if area and area.lower() != "all":
        out = [r for r in out if str(r.get("area") or "").lower() == area.lower()]
    if vendor and vendor.lower() != "all":
        out = [r for r in out if str(r.get("vendor") or "").lower() == vendor.lower()]
    if technology and technology.lower() != "all":
        needle = technology.lower()
        out = [r for r in out if needle in str(r.get("technology") or "").lower()]
    if severity and severity.lower() != "all":
        out = [r for r in out if str(r.get("severity") or "").lower() == severity.lower()]
    if search:
        q = search.lower()
        out = [
            r for r in out
            if q in str(r.get("title") or "").lower()
            or q in str(r.get("summary") or "").lower()
            or q in str(r.get("site_id") or "").lower()
            or any(q in str(c).lower() for c in r.get("cells") or [])
        ]
    return sorted(out, key=lambda r: (severity_rank(r.get("severity")), -float(r.get("score") or 0), r.get("title") or ""))


def summarize(rows: list[dict]) -> dict:
    by_severity: dict[str, int] = {}
    by_module: dict[str, int] = {}
    for row in rows:
        by_severity[str(row.get("severity") or "Info")] = by_severity.get(str(row.get("severity") or "Info"), 0) + 1
        by_module[str(row.get("module") or "Unknown")] = by_module.get(str(row.get("module") or "Unknown"), 0) + 1
    return {
        "total": len(rows),
        "by_severity": by_severity,
        "by_module": by_module,
    }

