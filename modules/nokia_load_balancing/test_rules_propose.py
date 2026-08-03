"""Tests for all-or-nothing AMLE parameter proposals."""

from modules.nokia_load_balancing.rules import propose_parameter_set


def test_all_three_change_for_lowest_source():
    row = {"cacHeadroom": 50, "deltaCac": 50, "maxCacThreshold": 50}
    params, proposed, blockers = propose_parameter_set(row, is_highest=False, is_lowest=True)
    assert blockers == []
    assert set(params) == {"cacHeadroom", "deltaCac", "maxCacThreshold"}
    assert params["cacHeadroom"]["proposed"] == 40
    assert params["deltaCac"]["proposed"] == 40
    assert params["maxCacThreshold"]["proposed"] == 60


def test_all_three_change_for_highest_source():
    row = {"cacHeadroom": 50, "deltaCac": 50, "maxCacThreshold": 50}
    params, proposed, blockers = propose_parameter_set(row, is_highest=True, is_lowest=False)
    assert blockers == []
    assert len(params) == 3
    assert params["cacHeadroom"]["proposed"] == 60
    assert params["deltaCac"]["proposed"] == 60
    assert params["maxCacThreshold"]["proposed"] == 40


def test_rejects_partial_when_one_param_clamped():
    row = {"cacHeadroom": 100, "deltaCac": 50, "maxCacThreshold": 50}
    params, proposed, blockers = propose_parameter_set(row, is_highest=True, is_lowest=False)
    assert params == {}
    assert "cacHeadroom: clamped at 100" in blockers[0]
    assert proposed["deltaCac"] == 60


def test_rejects_when_param_missing():
    row = {"cacHeadroom": 50, "deltaCac": 50}
    params, _, blockers = propose_parameter_set(row, is_highest=False, is_lowest=True)
    assert params == {}
    assert any("missing maxCacThreshold" in b for b in blockers)
