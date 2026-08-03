"""Tests for LNCEL IFS layer mapping."""

from modules.nokia_load_balancing.rules import (
    layer_from_lncel,
    lncels_for_sector_letter,
    target_layer_from_sector,
)


def test_layer_from_lncel_l18_ranges():
    for lncel in (1, 9, 50, 69):
        assert layer_from_lncel(lncel) == "L18"


def test_layer_from_lncel_l9_range():
    for lncel in (30, 31, 39):
        assert layer_from_lncel(lncel) == "L9"


def test_layer_from_lncel_l21_range():
    for lncel in (71, 75, 79):
        assert layer_from_lncel(lncel) == "L21"


def test_layer_from_lncel_l18_plus_range():
    for lncel in (81, 85, 89):
        assert layer_from_lncel(lncel) == "L18+"


def test_layer_from_lncel_other():
    assert layer_from_lncel(10) == "Other"
    assert layer_from_lncel(40) == "Other"
    assert layer_from_lncel("bad") == "Other"


def test_target_layer_from_sector_a():
    lncels = lncels_for_sector_letter("A")
    assert target_layer_from_sector(lncels, 1850) == "L18"
    assert target_layer_from_sector(lncels, 3749) == "L9"
    assert target_layer_from_sector(lncels, 300) == "L21"
    assert target_layer_from_sector(lncels, 325) == "L21"
    assert target_layer_from_sector(lncels, 1250) == "L18+"


def test_target_layer_from_sector_unknown_freq():
    lncels = lncels_for_sector_letter("A")
    assert target_layer_from_sector(lncels, 9999) == "Other"
