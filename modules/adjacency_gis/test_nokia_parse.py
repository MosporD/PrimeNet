"""Unit tests for Nokia BTS/TRX/ADCE parsing."""

from modules.adjacency_gis.nokia_parse import (
    BCCH_CHANNEL0_TYPE,
    build_sector_rows,
    is_admin_active,
    is_bcch_channel0_type,
    parent_bts_dn,
    parse_adce_record,
    parse_bts_record,
    parse_trx_bcch,
)


def test_is_bcch_channel0_type():
    assert is_bcch_channel0_type(4) is True
    assert is_bcch_channel0_type('4') is True
    assert is_bcch_channel0_type('MBCCH (4)') is True
    assert is_bcch_channel0_type(0) is False
    assert is_bcch_channel0_type('TCHF') is False


def test_is_admin_active():
    assert is_admin_active('unlocked') is True
    assert is_admin_active(0) is True
    assert is_admin_active('0') is True
    assert is_admin_active('locked') is False
    assert is_admin_active(1) is False


def test_parent_bts_dn():
    dn = 'PLMN-PLMN/BSC-1/BCF-2/BTS-10/TRX-1'
    assert parent_bts_dn(dn) == 'PLMN-PLMN/BSC-1/BCF-2/BTS-10'
    adce = 'PLMN-PLMN/BSC-1/BCF-2/BTS-10/ADCE-99'
    assert parent_bts_dn(adce) == 'PLMN-PLMN/BSC-1/BCF-2/BTS-10'


def test_parse_bts_skips_locked():
    mo = {
        'moId': 'PLMN/BSC-1/BCF-1/BTS-5',
        'parameters': {
            'segmentName': 'CELL_A',
            'cellId': 101,
            'adminState': 'locked',
        },
    }
    assert parse_bts_record(mo) is None


def test_parse_bts_active():
    mo = {
        'moId': 'PLMN/BSC-1/BCF-1/BTS-5',
        'parameters': {
            'segmentName': 'CELL_A',
            'cellId': 101,
            'adminState': 'unlocked',
        },
    }
    row = parse_bts_record(mo)
    assert row is not None
    assert row['segment_name'] == 'CELL_A'
    assert row['cell_id'] == 101
    assert row['bsc_id'] == '1'


def test_parse_trx_bcch_only_type_4():
    bts = 'PLMN/BSC-1/BCF-1/BTS-5'
    good = {
        'moId': f'{bts}/TRX-1',
        'parameters': {
            'channel0Type': BCCH_CHANNEL0_TYPE,
            'initialFrequency': 55,
            'adminState': 0,
        },
    }
    bad = {
        'moId': f'{bts}/TRX-2',
        'parameters': {
            'channel0Type': 0,
            'initialFrequency': 60,
            'adminState': 0,
        },
    }
    assert parse_trx_bcch(good)['bcch'] == 55
    assert parse_trx_bcch(bad) is None


def test_parse_adce():
    mo = {
        'moId': 'PLMN/BSC-1/BCF-1/BTS-5/ADCE-12',
        'parameters': {
            'adjacentCellIdCI': 202,
            'adjacentCellIdLac': 4100,
            'bcchFrequency': 55,
        },
    }
    row = parse_adce_record(mo)
    assert row['adj_ci'] == 202
    assert row['adj_lac'] == 4100
    assert row['bts_dn'] == 'PLMN/BSC-1/BCF-1/BTS-5'


def test_build_sector_rows_joins_bcch():
    bts = [{'dn': 'BTS-A', 'bsc_id': '1', 'bcf_id': '1', 'instance': '1',
            'segment_name': 'A', 'cell_name': 'A', 'cell_id': 1, 'admin_state': '0'}]
    bcch = {'BTS-A': {'dn': 'BTS-A/TRX-1', 'bcch': 99}}
    rows = build_sector_rows(bts, bcch)
    assert rows[0]['bcch'] == 99
    assert rows[0]['trx_dn'] == 'BTS-A/TRX-1'
