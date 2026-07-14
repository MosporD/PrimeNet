"""Tests for RET Management Huawei tilt unit handling."""

import pytest

from modules.ret_management.logic import (
    build_huawei_mod_command,
    mml_tilt_to_degrees_display,
    normalize_huawei_ret_rows,
    normalize_mml_tilt_input,
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
