"""Tests for SON Cluster / Anomaly / Topology builders (no torch, no metadata.db)."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


from modules.son_analytics.logic import (
    _build_anomaly_recommendations,
    _build_geo_cluster_recommendations,
    _build_topology_recommendations,
)

AREA = {
    "L18_A1": "Amman",
    "L18_A2": "Amman",
    "L18_A3": "Amman",
    "L18_A4": "Amman",
    "L18_B1": "Irbid",
    "L18_B2": "Irbid",
    "L18_Z1": "Zarqa",
    "L18_Z2": "Zarqa",
    "L18_Z3": "Zarqa",
    "L18_SOLO": "Aqaba",
}
LOC = {
    name: {"latitude": 31.95, "longitude": 35.91, "area": area, "site_id": "1004"}
    for name, area in AREA.items()
}


@contextmanager
def _isolated_maps():
    with (
        patch("modules.son_analytics.logic.get_cell_area_map", return_value=AREA),
        patch("modules.son_analytics.logic.get_cell_location_map", return_value=LOC),
        patch(
            "modules.son_analytics.logic._ml",
            return_value=(
                lambda: {"available": False},
                lambda: {},
                lambda probs: ("", 0.0) if not probs else (
                    max(probs, key=lambda k: float(probs[k] or 0)),
                    float(max(float(v or 0) for v in probs.values())),
                ),
                lambda cells, scores: 0.0,
            ),
        ),
    ):
        yield


def _deg(name, area="Amman", change=10.0):
    return {
        "cell_name": name,
        "area": area,
        "vendor": "nokia",
        "technology": "4G",
        "category": "Retainability",
        "change_pct": change,
        "history_days": 7,
        "latitude": 31.95,
        "longitude": 35.91,
    }


def _score(cell, *, anomaly=80.0, graph=0.0, spatial="", vendor="nokia", **extra):
    row = {
        "cell_name": cell,
        "anomaly_score": anomaly,
        "graph_score": graph,
        "spatial_cluster_id": spatial,
        "spatial_coherence": extra.pop("spatial_coherence", ""),
        "vendor": vendor,
        "rat": "4G",
        "day": "2026-08-29",
        "cause_probs": extra.pop("cause_probs", {"congestion": 0.8}),
        "top_kpis": extra.pop("top_kpis", []),
        "model_name": "iforest+pca",
    }
    row.update(extra)
    return row


def test_cluster_drops_groups_smaller_than_min():
    degraded = [
        _deg("L18_A1", change=12),
        _deg("L18_A2", change=11),
        _deg("L18_B1", area="Irbid", change=20),
        _deg("L18_B2", area="Irbid", change=18),
    ]
    with _isolated_maps():
        recs = _build_geo_cluster_recommendations(degraded, {})
    assert recs == []


def test_cluster_keeps_area_group_of_three():
    degraded = [
        _deg("L18_A1", change=12),
        _deg("L18_A2", change=11),
        _deg("L18_A3", change=10),
    ]
    with _isolated_maps():
        recs = _build_geo_cluster_recommendations(degraded, {})
    assert len(recs) == 1
    assert recs[0]["category"] == "Cluster"
    assert set(recs[0]["cells"]) == {"L18_A1", "L18_A2", "L18_A3"}
    assert recs[0]["evidence"]["spatial_cluster_id"] == ""


def test_cluster_prefers_spatial_key_over_area():
    degraded = [
        _deg("L18_A1", area="Amman"),
        _deg("L18_Z1", area="Zarqa"),
        _deg("L18_B1", area="Irbid"),
    ]
    scores = {
        "l18_a1": _score("L18_A1", spatial="s-9", spatial_coherence="tight"),
        "l18_z1": _score("L18_Z1", spatial="s-9", spatial_coherence="tight"),
        "l18_b1": _score("L18_B1", spatial="s-9", spatial_coherence="tight"),
    }
    with _isolated_maps():
        recs = _build_geo_cluster_recommendations(degraded, scores)
    assert len(recs) == 1
    assert recs[0]["evidence"]["spatial_cluster_id"] == "s-9"
    assert set(recs[0]["cells"]) == {"L18_A1", "L18_Z1", "L18_B1"}


def test_anomaly_ignores_scores_below_floor():
    scores = {
        "l18_a1": _score("L18_A1", anomaly=69.9),
        "l18_a2": _score("L18_A2", anomaly=70.0),
    }
    with _isolated_maps():
        recs = _build_anomaly_recommendations([], scores, set())
    names = {r["cells"][0] for r in recs}
    assert "L18_A1" not in names
    assert "L18_A2" in names


def test_anomaly_skips_clustered_cells():
    scores = {"l18_a1": _score("L18_A1", anomaly=95)}
    with _isolated_maps():
        recs = _build_anomaly_recommendations([], scores, {"l18_a1"})
    assert recs == []


def test_anomaly_marks_missed_by_wow():
    scores = {"l18_solo": _score("L18_SOLO", anomaly=88)}
    degraded = [_deg("L18_A1")]
    with _isolated_maps():
        recs = _build_anomaly_recommendations(degraded, scores, set())
    assert len(recs) == 1
    assert recs[0]["evidence"]["missed_by_wow"] is True
    assert "slow drift" in recs[0]["summary"]


def test_anomaly_dedupes_vendor_alias_keys():
    row = _score("L18_A1", anomaly=91)
    scores = {"l18_a1": row, "nokia|l18_a1": row}
    with _isolated_maps():
        recs = _build_anomaly_recommendations([], scores, set())
    assert len(recs) == 1


def test_topology_ignores_graph_below_floor():
    scores = {
        "l18_a1": _score("L18_A1", graph=54.9),
        "l18_a2": _score("L18_A2", graph=55.0),
    }
    with _isolated_maps():
        recs = _build_topology_recommendations(scores, set())
    names = {r["cells"][0] for r in recs}
    assert "L18_A1" not in names
    assert "L18_A2" in names


def test_topology_skips_clustered_cells():
    scores = {"l18_a1": _score("L18_A1", graph=90)}
    with _isolated_maps():
        recs = _build_topology_recommendations(scores, {"l18_a1"})
    assert recs == []


def test_rules_only_empty_scores_yields_no_anomaly_or_topology():
    degraded = [_deg("L18_A1"), _deg("L18_A2"), _deg("L18_A3")]
    with _isolated_maps():
        clusters = _build_geo_cluster_recommendations(degraded, {})
        anomalies = _build_anomaly_recommendations(degraded, {}, set())
        topology = _build_topology_recommendations({}, set())
    assert len(clusters) == 1
    assert clusters[0]["category"] == "Cluster"
    assert anomalies == []
    assert topology == []


if __name__ == "__main__":
    import sys

    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, exc)
    sys.exit(1 if failed else 0)
