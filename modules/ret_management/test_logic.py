"""Tests for RET Management Huawei tilt unit handling and Nokia RETU helpers."""

import pytest

from modules.ret_management.logic import (
    NOKIA_MO_CLASS_READ_FALLBACK,
    NOKIA_MO_CLASS_WRITE_FALLBACK,
    _score_mo_adaptation,
    annotate_ret_rows,
    build_huawei_mod_command,
    config_retu_dist_name,
    huawei_ret_sector_key,
    mml_tilt_to_degrees_display,
    nokia_ret_sector_key,
    normalize_huawei_ret_rows,
    normalize_mml_tilt_input,
    resolve_nokia_retu_read_mo_class,
    resolve_nokia_retu_write_mo_class,
    sort_huawei_ret_rows,
    sort_nokia_retu_rows,
)


def test_mml_tilt_to_degrees_display():
    assert mml_tilt_to_degrees_display('40') == '4'
    assert mml_tilt_to_degrees_display('80') == '8'
    assert mml_tilt_to_degrees_display('85') == '8.5'
    assert mml_tilt_to_degrees_display('32767') == ''


def test_normalize_mml_tilt_input_passes_through_mml_units():
    assert normalize_mml_tilt_input('40') == '40'
    assert normalize_mml_tilt_input('80') == '80'


def test_normalize_mml_tilt_input_rejects_invalid():
    with pytest.raises(ValueError, match='required'):
        normalize_mml_tilt_input('')
    with pytest.raises(ValueError, match='MML integer'):
        normalize_mml_tilt_input('4.0')
    with pytest.raises(ValueError, match='MML integer'):
        normalize_mml_tilt_input('abc')


def test_build_huawei_mod_command_matches_manual_mml():
    cmd = build_huawei_mod_command(device_no='21', subunit_no='1', tilt='40')
    assert cmd == 'MOD RETSUBUNIT:DEVICENO=21,SUBUNITNO=1,TILT=40;'


def test_normalize_huawei_ret_rows_keeps_mml_values():
    rows = normalize_huawei_ret_rows([
        {
            'Device No.': '21',
            'Subunit No.': '1',
            'Tilt': '40',
            'Actual Tilt': '40',
            'Online Status': 'Online',
        },
    ])
    assert rows[0]['Tilt'] == '40'
    assert rows[0]['Actual Tilt'] == '40'


def test_score_mo_adaptation_read_prefers_eqmr():
    assert _score_mo_adaptation('com.nokia.srbts.eqmr', prefer_runtime=True) > _score_mo_adaptation(
        'com.nokia.srbts.eqm', prefer_runtime=True
    )


def test_score_mo_adaptation_write_prefers_eqm():
    assert _score_mo_adaptation('com.nokia.srbts.eqm', prefer_runtime=False) > _score_mo_adaptation(
        'com.nokia.srbts.eqmr', prefer_runtime=False
    )


def test_resolve_nokia_retu_mo_class_fallbacks_without_client():
    assert resolve_nokia_retu_read_mo_class(None) == NOKIA_MO_CLASS_READ_FALLBACK
    assert resolve_nokia_retu_write_mo_class(None) == NOKIA_MO_CLASS_WRITE_FALLBACK


def test_config_retu_dist_name_from_configdn():
    assert config_retu_dist_name({
        'configDN': 'MRBTS-51021/EQM-1/APEQM-1/ALD-2/RETU-1',
        'DN': 'PLMN-PLMN/MRBTS-51021/EQM_R-1/APEQM_R-1/ALD_R-2/RETU_R-1',
    }) == 'PLMN-PLMN/MRBTS-51021/EQM-1/APEQM-1/ALD-2/RETU-1'


def test_config_retu_dist_name_from_runtime_dn():
    assert config_retu_dist_name({
        'DN': 'PLMN-PLMN/MRBTS-51021/EQM_R-1/APEQM_R-1/ALD_R-2/RETU_R-1',
    }) == 'PLMN-PLMN/MRBTS-51021/EQM-1/APEQM-1/ALD-2/RETU-1'


def _huawei_rows():
    return [
        {'Device No.': '21', 'Subunit No.': '10', 'Subunit Name': 'SEC3'},
        {'Device No.': '3', 'Subunit No.': '1', 'Subunit Name': 'SEC1'},
        {'Device No.': '21', 'Subunit No.': '2', 'Subunit Name': 'SEC2'},
    ]


def test_sort_huawei_ret_rows_is_numeric_and_reproducible():
    """Same input in any order must produce the same table order."""
    expected = [('3', '1'), ('21', '2'), ('21', '10')]
    rows = _huawei_rows()
    for candidate in (rows, list(reversed(rows)), rows[1:] + rows[:1]):
        ordered = sort_huawei_ret_rows(candidate)
        assert [(r['Device No.'], r['Subunit No.']) for r in ordered] == expected


def test_sort_huawei_ret_rows_tolerates_blank_and_text_keys():
    rows = [
        {'Device No.': '', 'Subunit No.': '', 'Tilt': '40'},
        {'Device No.': 'N/A', 'Subunit No.': '1', 'Tilt': '40'},
        {'Device No.': '2', 'Subunit No.': '1', 'Tilt': '40'},
    ]
    ordered = sort_huawei_ret_rows(rows)
    assert [r['Device No.'] for r in ordered] == ['2', 'N/A', '']


def test_sort_nokia_retu_rows_orders_by_sector_then_subunit():
    rows = [
        {'DN': 'a/RETU-1', 'sectorID': '2', 'subunitNumber': '1'},
        {'DN': 'b/RETU-10', 'sectorID': '1', 'subunitNumber': '10'},
        {'DN': 'c/RETU-2', 'sectorID': '1', 'subunitNumber': '2'},
    ]
    ordered = sort_nokia_retu_rows(rows)
    assert [r['DN'] for r in ordered] == ['c/RETU-2', 'b/RETU-10', 'a/RETU-1']


def test_sort_nokia_retu_rows_natural_dn_order():
    rows = [
        {'DN': 'x/RETU-10', 'sectorID': '1', 'subunitNumber': '1'},
        {'DN': 'x/RETU-2', 'sectorID': '1', 'subunitNumber': '1'},
    ]
    assert [r['DN'] for r in sort_nokia_retu_rows(rows)] == ['x/RETU-2', 'x/RETU-10']


def test_huawei_ret_sector_key_prefers_actual_sector_id():
    assert huawei_ret_sector_key({
        'Device No.': '21', 'Subunit No.': '1',
        'Subunit Name': 'SEC3', 'Actual Sector ID': '2',
    }) == '2'


def test_huawei_ret_sector_key_from_subunit_name():
    assert huawei_ret_sector_key({'Subunit Name': 'SEC3'}) == '3'
    assert huawei_ret_sector_key({'Subunit Name': 'Sector-2'}) == '2'
    assert huawei_ret_sector_key({'Subunit Name': 'B'}) == '2'


def test_huawei_ret_sector_key_unknown_stays_empty():
    assert huawei_ret_sector_key({'Subunit Name': 'spare'}) == ''
    assert huawei_ret_sector_key({'Device No.': '21', 'Subunit No.': '4'}) == ''


def test_nokia_ret_sector_key_falls_back_to_subunit_number():
    assert nokia_ret_sector_key({'sectorID': '3'}) == '3'
    assert nokia_ret_sector_key({'sectorID': '', 'subunitNumber': '2'}) == '2'
    assert nokia_ret_sector_key({'sectorID': '', 'subunitNumber': ''}) == ''


def test_annotate_ret_rows_huawei_keys_and_sectors():
    rows = annotate_ret_rows(
        [{'Device No.': '21', 'Subunit No.': '1', 'Actual Sector ID': '1', 'Tilt': '40'}],
        vendor='huawei',
    )
    assert rows[0]['_ret_key'] == '21:1'
    assert rows[0]['_ret_sector'] == '1'


def test_annotate_ret_rows_nokia_keys_sector_and_bearing():
    rows = annotate_ret_rows(
        [{
            'DN': 'PLMN-PLMN/MRBTS-51021/EQM-1/APEQM-1/ALD-1/RETU-1',
            'sectorID': '1',
            'antBearing': '370.5',
        }],
        vendor='nokia',
    )
    assert rows[0]['_ret_key'].endswith('/RETU-1')
    assert rows[0]['_ret_sector'] == '1'
    assert rows[0]['_ret_azimuth'] == 10.5


def test_annotate_ret_rows_disambiguates_duplicate_identities():
    rows = annotate_ret_rows(
        [{'Device No.': '1', 'Subunit No.': '1'}, {'Device No.': '1', 'Subunit No.': '1'}],
        vendor='huawei',
    )
    assert [r['_ret_key'] for r in rows] == ['1:1', '1:1#2']


def test_annotate_ret_rows_ignores_non_numeric_bearing():
    rows = annotate_ret_rows([{'DN': 'a/RETU-1', 'antBearing': 'n/a'}], vendor='nokia')
    assert '_ret_azimuth' not in rows[0]


def test_sort_huawei_ret_rows_treats_nan_as_text():
    """A NaN in a sort key would make every comparison false and reshuffle rows."""
    rows = [
        {'Device No.': 'nan', 'Subunit No.': '1'},
        {'Device No.': '2', 'Subunit No.': '1'},
        {'Device No.': 'inf', 'Subunit No.': '1'},
    ]
    ordered = [r['Device No.'] for r in sort_huawei_ret_rows(rows)]
    assert ordered == [r['Device No.'] for r in sort_huawei_ret_rows(list(reversed(rows)))]
    assert ordered[0] == '2'
