"""Tests for RET Management Huawei tilt unit handling and Nokia RETU helpers."""

import pytest

from modules.ret_management.logic import (
    NOKIA_MO_CLASS_READ_FALLBACK,
    NOKIA_MO_CLASS_WRITE_FALLBACK,
    _score_mo_adaptation,
    build_huawei_mod_command,
    config_retu_dist_name,
    mml_tilt_to_degrees_display,
    normalize_huawei_ret_rows,
    normalize_mml_tilt_input,
    resolve_nokia_retu_read_mo_class,
    resolve_nokia_retu_write_mo_class,
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
