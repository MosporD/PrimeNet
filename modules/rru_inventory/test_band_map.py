"""Unit tests for RMOD cell-list → band mapping (no live NetAct)."""

from __future__ import annotations

from modules.rru_inventory.band_map import (
    BandIndex,
    band_techs_for_rmod,
    parse_cell_tokens,
    uarfcn_to_band,
)
from modules.rru_inventory.logic import build_sankey_payload


def test_parse_cell_tokens() -> None:
    assert parse_cell_tokens('3,73') == ['3', '73']
    assert parse_cell_tokens('LNCEL-81,LNCEL-83') == ['81', '83']
    assert parse_cell_tokens(['1', '2']) == ['1', '2']
    assert parse_cell_tokens({'items': [{'dn': 'WCEL-5'}, {'dn': 'WCEL-6'}]}) == ['5', '6']
    assert parse_cell_tokens('') == []


def test_uarfcn_to_band() -> None:
    assert uarfcn_to_band('10562') == 'U2100'
    assert uarfcn_to_band('10762') == 'U2100'
    assert uarfcn_to_band('3048') == 'U900'


def test_band_techs_lte_fan_out() -> None:
    index = BandIndex()
    index.lte_by_site_cell[('103', '3')] = 'L18'
    index.lte_by_site_cell[('103', '73')] = 'L21'

    techs = band_techs_for_rmod(
        {
            'site_id': '103',
            'metadata_site_id': '103',
            'activeGsmCellsList': '',
            'activeWcdmaCellsList': '',
            'activeLteCellsList': '3,73',
            'activeNrCellsList': '',
        },
        band_index=index,
    )
    assert techs == ['4G-L18', '4G-L21']


def test_band_techs_3g_site_fallback() -> None:
    index = BandIndex()
    index.wcdma_site_bands['103'] = {'U2100'}
    # List locals 0,14 do not match CI — site fallback still yields U2100.
    techs = band_techs_for_rmod(
        {
            'site_id': '103',
            'metadata_site_id': '103',
            'activeWcdmaCellsList': '0,14',
            'activeLteCellsList': '',
            'activeGsmCellsList': '',
            'activeNrCellsList': '',
        },
        band_index=index,
    )
    assert techs == ['3G-U2100']


def test_network_view_sankey_skips_area() -> None:
    rows = [
        {
            'area': 'East Amman',
            'productName': 'RRU_A',
            'techs': ['4G-L18', '4G-L21'],
            'unused': False,
            'multi_rat': False,
        },
        {
            'area': 'West Amman',
            'productName': 'RRU_B',
            'techs': ['3G-U2100'],
            'unused': False,
            'multi_rat': False,
        },
    ]
    payload = build_sankey_payload(rows, network_view=True)
    assert payload['network_view'] is True
    assert payload['summary']['areas'] == 0
    kinds = {n['name']: n['kind'] for n in payload['nodes']}
    assert 'East Amman' not in kinds
    assert 'West Amman' not in kinds
    assert kinds['4G-L18'] == 'tech'
    assert kinds['RRU_A'] == 'rru'
    sources = {link['source_id'] for link in payload['links']}
    assert 'East Amman' not in sources
    assert '4G-L18' in sources
