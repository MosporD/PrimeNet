"""Tests for Huawei CellMLB proposals."""

from modules.huawei_load_balancing.export import build_mml
from modules.huawei_load_balancing.logic import analyze_sectors
from modules.huawei_load_balancing.rules import propose_parameter_set


def test_highest_lowers_mlb_thresholds():
    params, _, blockers = propose_parameter_set(None, is_highest=True, is_lowest=False)
    assert blockers == []
    assert params["IdleMlbUeNumThd"]["proposed"] == 8
    assert params["HoMlbUeNumThd"]["proposed"] == 15


def test_lowest_raises_mlb_thresholds():
    params, _, blockers = propose_parameter_set(None, is_highest=False, is_lowest=True)
    assert blockers == []
    assert params["IdleMlbUeNumThd"]["proposed"] == 12
    assert params["HoMlbUeNumThd"]["proposed"] == 25


def test_analyze_two_layer_sector():
    result = analyze_sectors([{
        "sector_id": "1201_A",
        "throughput": {"L18": 40.0, "L21": 10.0, "L9": 0, "L18+": 0},
    }])
    assert result["success"] is True
    assert result["change_count"] >= 4
    text = build_mml(result["changes"])
    assert "MOD CELLMLB" in text
    assert "IdleMlbUeNumThd" in text
