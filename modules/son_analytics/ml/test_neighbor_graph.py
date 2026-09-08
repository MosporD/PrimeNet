"""Unit tests for SON neighbor aggregation and graph isolation."""

from __future__ import annotations

import sys
from pathlib import Path

from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.son_analytics.ml.models.graph import graph_scores
from modules.son_analytics.ml.neighbor_agg import aggregate_pairs, attach_neighbor_features


def _numpy_graph(rows, emb, adj):
    with patch("modules.son_analytics.ml.models.graph.cfg.torch_enabled", return_value=False):
        return graph_scores(rows, emb, adj)


def test_aggregate_pairs_reciprocal_and_cap():
    pairs = [
        ("a", "b", "A", "B", 100.0, 90.0),
        ("b", "a", "B", "A", 80.0, 92.0),
        ("a", "c", "A", "C", 10.0, 70.0),
    ]
    stats, adj = aggregate_pairs(pairs)
    assert stats["a"]["nbr_count"] == 2.0
    assert stats["a"]["nbr_missing_recip"] == 0.5
    assert adj["a"][0] == "b"
    assert "c" in adj["a"]
    assert stats["b"]["nbr_missing_recip"] == 0.0


def test_attach_uses_precomputed_stats():
    rows = [
        {"cell_name": "A", "latitude": 31.9, "longitude": 35.9},
        {"cell_name": "B", "latitude": 31.91, "longitude": 35.91},
    ]
    stats, adj = aggregate_pairs([("a", "b", "A", "B", 50.0, 99.0), ("b", "a", "B", "A", 40.0, 98.0)])
    attach_neighbor_features(rows, "nokia", stats=stats, adj=adj)
    assert rows[0]["nbr_count"] == 1.0
    assert rows[0]["nbr_distance_km"] > 0


def test_graph_isolation_rises_when_neighbor_embedding_diverges():
    rows = [
        {"cell_name": "A", "nbr_missing_recip": 0, "nbr_distance_km": 1, "nbr_ho_sr": 99},
        {"cell_name": "B", "nbr_missing_recip": 0, "nbr_distance_km": 1, "nbr_ho_sr": 99},
        {"cell_name": "C", "nbr_missing_recip": 0, "nbr_distance_km": 1, "nbr_ho_sr": 99},
    ]
    emb = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]
    adj = {"a": ["b", "c"], "b": ["a"], "c": ["a"]}
    scores = _numpy_graph(rows, emb, adj)
    assert scores[0] > scores[1]
    assert scores[0] > 10.0


def test_graph_no_match_does_not_invent_isolation():
    rows = [
        {"cell_name": "A", "nbr_missing_recip": 0, "nbr_distance_km": 0, "nbr_ho_sr": 99},
    ]
    scores = _numpy_graph(rows, [[1.0, 0.0]], {})
    assert scores == [0.0]


def test_graph_ho_penalty_without_embedding_neighbors():
    rows = [
        {
            "cell_name": "A",
            "nbr_missing_recip": 1.0,
            "nbr_distance_km": 20,
            "nbr_ho_sr": 80,
        },
    ]
    scores = _numpy_graph(rows, [[1.0, 0.0]], {})
    assert scores[0] >= 55.0


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, exc)
    raise SystemExit(1 if failed else 0)
