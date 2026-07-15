"""Tests for performance dictionary Nokia loader."""

from modules.performance_dictionary.nokia_loader import (
    _normalize_counter_id,
    _normalize_measurement_id,
    _parse_measurement_id_and_name,
    _source_technology_hint,
    _store_key,
    _tech_tokens,
    load_nokia_data,
)


def test_normalize_counter_id():
    assert _normalize_counter_id(1000) == "001000"
    assert _normalize_counter_id("1000") == "001000"
    assert _normalize_counter_id("M802C0") == "M802C0"


def test_normalize_measurement_id():
    assert _normalize_measurement_id(5000) == "5000"
    assert _normalize_measurement_id("5000.0") == "5000"


def test_tech_tokens():
    assert _tech_tokens("SRAN,5G") == ["SRAN", "5G"]
    assert _tech_tokens("3G-RNC, 3G-BTS") == ["3G-RNC", "3G-BTS"]


def test_source_technology_hint():
    assert _source_technology_hint("asbsc_measurements_counters_and_kpis_fp24r3.xls") == "2G-BSC"
    assert _source_technology_hint("WCDMA_RAN_Key_Performance_Indicators.xls") == "3G-RNC"
    assert _source_technology_hint("IPA_RNC_and_Multicontroller_RNC_Counters_and_Performance_Measurements.xls") == "3G-RNC"
    assert _source_technology_hint("ref_bts_performance_measurements_22R4_22R3.xlsx") == ""


def test_parse_measurement_id_and_name():
    assert _parse_measurement_id_and_name("001: Traffic") == ("1", "Traffic")
    assert _parse_measurement_id_and_name("802: RNC Capacity Usage") == ("802", "RNC Capacity Usage")


def test_store_key():
    assert _store_key("2G-BSC", "1") == "2G-BSC|1"


def test_load_nokia_data_has_entries():
    data = load_nokia_data(force_refresh=True)
    assert data.get("measurement_index")
    assert data.get("kpi_index")
    meta = data.get("meta") or {}
    assert meta.get("measurement_count", 0) > 400
    assert meta.get("counter_count", 0) > 30000
    assert meta.get("kpi_count", 0) > 3000
    techs = set(meta.get("technologies") or [])
    assert "2G-BSC" in techs
    assert "3G-RNC" in techs
    sources = " ".join(meta.get("source") or []).lower()
    assert "asbsc" in sources
    assert "wcdma" in sources or "ipa_rnc" in sources
