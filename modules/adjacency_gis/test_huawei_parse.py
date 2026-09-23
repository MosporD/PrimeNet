"""Unit tests for Huawei GTRX / G2GNCELL parsing."""

from modules.adjacency_gis.huawei_parse import (
    is_main_bcch_trx,
    is_trx_active,
    join_trx_with_gcell,
    parse_g2gncell_row,
    parse_gcell_row,
    parse_gtrx_bcch_row,
)


def test_is_main_bcch_trx():
    assert is_main_bcch_trx('YES') is True
    assert is_main_bcch_trx('Yes') is True
    assert is_main_bcch_trx('1') is True
    assert is_main_bcch_trx('NO') is False
    assert is_main_bcch_trx('') is False


def test_is_trx_active():
    assert is_trx_active('Activated', 'Unlocked') is True
    assert is_trx_active('Active', 'unlocked') is True
    assert is_trx_active('Deactivated', 'Unlocked') is False
    assert is_trx_active('Activated', 'Locked') is False


def test_parse_gtrx_bcch_row():
    row = {
        'BSC Name': 'BSC_HQ',
        'Cell Index': 12,
        'TRX ID': 0,
        'TRX Name': 'TRX_A',
        'Frequency': 55,
        'Is Main BCCH TRX': 'YES',
        'TRX No.': 0,
        'Active Status': 'Activated',
        'Administrative State': 'Unlocked',
    }
    parsed = parse_gtrx_bcch_row(row)
    assert parsed is not None
    assert parsed['bcch'] == 55
    assert parsed['cell_index'] == 12
    assert parsed['bsc_id'] == 'BSC_HQ'
    assert parsed['vendor'] == 'huawei'


def test_parse_gtrx_skips_non_bcch():
    row = {
        'Cell Index': 12,
        'Frequency': 60,
        'Is Main BCCH TRX': 'NO',
        'Active Status': 'Activated',
        'Administrative State': 'Unlocked',
    }
    assert parse_gtrx_bcch_row(row) is None


def test_parse_gcell_and_join():
    gcell = parse_gcell_row({
        'BSC Name': 'BSC_HQ',
        'Cell Index': 12,
        'Cell Name': 'CELL_HW_A',
        'CI': 101,
        'LAC': 4100,
        'BCCH': 55,
    })
    assert gcell['cell_name'] == 'CELL_HW_A'
    trx = parse_gtrx_bcch_row({
        'BSC Name': 'BSC_HQ',
        'Cell Index': 12,
        'TRX ID': 0,
        'Frequency': 55,
        'Is Main BCCH TRX': 'YES',
        'Active Status': 'Activated',
        'Administrative State': 'Unlocked',
    })
    sectors = join_trx_with_gcell(
        [trx],
        {('bsc_hq', 12): gcell},
    )
    assert len(sectors) == 1
    assert sectors[0]['cell_name'] == 'CELL_HW_A'
    assert sectors[0]['cell_id'] == 101


def test_parse_g2gncell_row():
    row = {
        'BSC Name': 'BSC_HQ',
        'Cell Index': 12,
        'NCell CI': 202,
        'NCell LAC': 4100,
        'Neighbor Cell Name': 'CELL_B',
        'BCCH': 60,
    }
    parsed = parse_g2gncell_row(row)
    assert parsed['source_cell_index'] == 12
    assert parsed['adj_ci'] == 202
    assert parsed['adj_lac'] == 4100
    assert parsed['vendor'] == 'huawei'
