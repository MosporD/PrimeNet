"""Tests for canonical site_id → area routing."""

from core.site_area import (
    MANUAL_SITE_AREAS,
    area_table_slug,
    base_pm_table_name,
    canonicalize_area,
    derive_area_from_cluster_map,
    is_pm_partition_of,
    list_pm_partition_tables,
    normalize_site_id,
    pm_area_table_name,
    preferred_pm_table,
    resolve_cell_area,
    resolve_site_area,
    site_id_from_cell_name,
)


def test_normalize_netact_prefixes():
    assert normalize_site_id("64415") == "4415"
    assert normalize_site_id("53306") == "3306"
    assert normalize_site_id("50308") == "308"
    assert normalize_site_id("50801") == "801"
    # UL short ids must not be stripped
    assert normalize_site_id("6001") == "6001"
    assert normalize_site_id("6400") == "6400"
    assert normalize_site_id("201") == "201"


def test_cluster_map_areas():
    assert derive_area_from_cluster_map("201") == "West Amman"
    assert derive_area_from_cluster_map("308") == "East Amman"
    assert derive_area_from_cluster_map("3306") == "South Jordan"
    assert derive_area_from_cluster_map("4415") == "North Jordan"
    assert derive_area_from_cluster_map("64415") == "North Jordan"  # after strip


def test_manual_overrides():
    assert MANUAL_SITE_AREAS["6008"] == "North Jordan"
    assert MANUAL_SITE_AREAS["6068"] == "South Jordan"
    assert MANUAL_SITE_AREAS["6069"] == "South Jordan"
    assert MANUAL_SITE_AREAS["6074"] == "North Jordan"
    assert MANUAL_SITE_AREAS["6086"] == "South Jordan"
    assert MANUAL_SITE_AREAS["6150"] == "South Jordan"
    assert MANUAL_SITE_AREAS["6484"] == "South Jordan"
    assert MANUAL_SITE_AREAS["6485"] == "South Jordan"
    assert MANUAL_SITE_AREAS["9999"] == "South Amman"
    for sid in MANUAL_SITE_AREAS:
        assert resolve_site_area(sid) == MANUAL_SITE_AREAS[sid]


def test_canonicalize_aliases():
    assert canonicalize_area("North") == "North Jordan"
    assert canonicalize_area("Zarqa") == "East Jordan"
    assert canonicalize_area("west amman") == "West Amman"


def test_table_slug():
    assert area_table_slug("West Amman") == "WEST_AMMAN"
    assert pm_area_table_name("4G_CELLS_HOURLY", "West Amman") == "4G_CELLS_HOURLY__WEST_AMMAN"
    assert preferred_pm_table("4G_CELLS_HOURLY", "201") == "4G_CELLS_HOURLY__WEST_AMMAN"
    assert preferred_pm_table("4G_CELLS_HOURLY", "6008") == "4G_CELLS_HOURLY__NORTH_JORDAN"
    assert is_pm_partition_of("4G_CELLS_HOURLY__WEST_AMMAN", "4G_CELLS_HOURLY")
    assert base_pm_table_name("4G_CELLS_HOURLY__WEST_AMMAN") == "4G_CELLS_HOURLY"
    assert list_pm_partition_tables(
        ["4G_CELLS_HOURLY", "4G_CELLS_HOURLY__WEST_AMMAN", "3G_CELLS_HOURLY"],
        "4G_CELLS_HOURLY",
    ) == ["4G_CELLS_HOURLY", "4G_CELLS_HOURLY__WEST_AMMAN"]


def test_site_id_from_cell_name():
    assert site_id_from_cell_name("4415-L1") == "4415"
    assert site_id_from_cell_name("64415_L21") == "4415"
    assert resolve_cell_area("6008-X") == "North Jordan"
