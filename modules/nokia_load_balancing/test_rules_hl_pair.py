"""Tests for highest↔lowest AMLEPR pair filtering."""

from modules.nokia_load_balancing.rules import qualifies_highest_lowest_pair


def test_highest_to_lowest_qualifies():
    ok, is_high = qualifies_highest_lowest_pair("L18", "L9", "L18", "L9")
    assert ok is True
    assert is_high is True


def test_lowest_to_highest_qualifies():
    ok, is_high = qualifies_highest_lowest_pair("L9", "L18", "L18", "L9")
    assert ok is True
    assert is_high is False


def test_other_target_layer_rejected():
    ok, _ = qualifies_highest_lowest_pair("L18", "L21", "L18", "L9")
    assert ok is False


def test_other_source_layer_rejected():
    ok, _ = qualifies_highest_lowest_pair("L21", "L9", "L18", "L9")
    assert ok is False


def test_l18_plus_pair():
    ok_high, _ = qualifies_highest_lowest_pair("L18", "L18+", "L18", "L18+")
    ok_low, is_high = qualifies_highest_lowest_pair("L18+", "L18", "L18", "L18+")
    assert ok_high is True
    assert ok_low is True and is_high is False


def test_missing_reverse_direction():
    from modules.nokia_load_balancing.rules import missing_hl_direction_warnings

    msgs = missing_hl_direction_warnings("5635_A", "L18", "L18+", {("L18", "L18+")})
    assert len(msgs) == 1
    assert "missing AMLEPR L18+→L18" in msgs[0]
    assert "configuration gap" in msgs[0]


def test_complete_pair_no_gap_warning():
    from modules.nokia_load_balancing.rules import missing_hl_direction_warnings

    present = {("L18", "L9"), ("L9", "L18")}
    assert missing_hl_direction_warnings("1201_A", "L18", "L9", present) == []

