"""Capacity Hotspots ranks by load and ignores drops; neighbor sampling never claims a missing reverse."""

from __future__ import annotations

import core.radio.insights as ins
import core.radio.metadata as md
import core.radio.mobility as mob
import core.radio.neighbor as nb
from modules.network_health.logic import _sort_kpi_cell_rows


def test_highest_sort_puts_most_loaded_first():
    rows = [
        {"cell_name": "A1", "post": 40.0, "delta": 20.0},
        {"cell_name": "Z9", "post": 95.0, "delta": 0.0},
        {"cell_name": "M5", "post": None, "delta": 5.0},
    ]
    assert [r["cell_name"] for r in _sort_kpi_cell_rows(rows, "highest")] == ["Z9", "A1", "M5"]


def test_capacity_scores_growth_not_drops(monkeypatch):
    rows = [
        {"cell_name": "UP", "kpi": "DL PRB Usage Rate(%)", "pre": 70.0, "post": 92.0, "delta": 22.0},
        {"cell_name": "DOWN", "kpi": "DL PRB Usage Rate(%)", "pre": 60.0, "post": 30.0, "delta": -30.0},
    ]
    monkeypatch.setattr(ins.pm, "top_kpi_rows", lambda **kw: [dict(r) for r in rows])
    monkeypatch.setattr(ins.metadata, "cell_index", lambda: {})
    out = ins.capacity_hotspots(vendor="huawei", technology="4G-FDD", limit=50, force_refresh=True)
    assert [i["cells"][0] for i in out["issues"]] == ["UP"]


def test_unseen_reverse_relation_is_unknown_not_missing(monkeypatch):
    lines = [{
        "source_cell": "A", "target_cell": "B", "ho_attempts": 1000.0, "ho_success_rate": 80.0,
        "ho_failures": 200.0, "distance_km": 1.0, "vendor": "Huawei", "technology": "4G-4G",
    }]
    monkeypatch.setattr(nb, "load_neighbor_lines", lambda *a, **k: [dict(r) for r in lines])
    monkeypatch.setattr(nb, "neighbor_freshness", lambda: {})
    monkeypatch.setattr(md, "cell_index", lambda: {})
    issues = nb.build_quality_issues("huawei", "4G-4G", limit=10)
    assert issues and issues[0]["evidence"]["reverse_relation"] == "unknown"
    assert "reciprocal" not in issues[0]["summary"]
    rows = mob.mobility_explorer(vendor="huawei", technology="4G-4G", limit=10, force_refresh=True)["issues"]
    assert rows and "one-way" not in rows[0]["summary"]
