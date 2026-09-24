"""Unit tests for Adjacency GIS audit logic (uni/bi, co-channel, NCL limit)."""

from __future__ import annotations

from unittest.mock import patch

from modules.adjacency_gis.logic import build_map_payload, haversine_km


def _meta_index():
    a = {
        'cell_name': 'CELL_A',
        'site_id': 'S1',
        'site_name': 'Site1',
        'cell_id': 101,
        'lac': 1,
        'bcch': 55,
        'lat': 31.95,
        'lng': 35.93,
        'azimuth': 0,
        'area': 'Amman',
        'vendor': 'nokia',
        'frequency_band': 'GSM900',
    }
    b = {
        'cell_name': 'CELL_B',
        'site_id': 'S2',
        'site_name': 'Site2',
        'cell_id': 202,
        'lac': 1,
        'bcch': 55,  # same BCCH → co-channel when linked
        'lat': 31.96,
        'lng': 35.94,
        'azimuth': 180,
        'area': 'Amman',
        'vendor': 'nokia',
        'frequency_band': 'GSM900',
    }
    c = {
        'cell_name': 'CELL_C',
        'site_id': 'S3',
        'site_name': 'Site3',
        'cell_id': 303,
        'lac': 1,
        'bcch': 60,
        'lat': 32.10,
        'lng': 36.10,
        'azimuth': 90,
        'area': 'Zarqa',
        'vendor': 'nokia',
        'frequency_band': 'GSM900',
    }
    by_name = {k['cell_name'].lower(): k for k in (a, b, c)}
    by_cell_id = {str(k['cell_id']): k for k in (a, b, c)}
    by_ci_lac = {(k['cell_id'], k['lac']): k for k in (a, b, c)}
    by_ci = {k['cell_id']: [k] for k in (a, b, c)}
    return {
        'by_name': by_name,
        'by_cell_id': by_cell_id,
        'by_ci_lac': by_ci_lac,
        'by_ci': by_ci,
    }


def test_haversine_positive():
    d = haversine_km(31.95, 35.93, 31.96, 35.94)
    assert d > 0
    assert d < 5


@patch('modules.adjacency_gis.logic.load_cells_2g_index', side_effect=_meta_index)
def test_bidirectional_and_unidirectional(_mock_idx):
    sectors = [
        {'dn': 'BTS-A', 'bsc_id': '1', 'segment_name': 'CELL_A', 'cell_name': 'CELL_A',
         'cell_id': 101, 'bcch': 55, 'admin_state': '0'},
        {'dn': 'BTS-B', 'bsc_id': '1', 'segment_name': 'CELL_B', 'cell_name': 'CELL_B',
         'cell_id': 202, 'bcch': 55, 'admin_state': '0'},
    ]
    edges = [
        {'dn': 'ADCE-1', 'source_dn': 'BTS-A', 'adj_ci': 202, 'adj_lac': 1, 'bcch_frequency': 55},
        {'dn': 'ADCE-2', 'source_dn': 'BTS-B', 'adj_ci': 101, 'adj_lac': 1, 'bcch_frequency': 55},
        {'dn': 'ADCE-3', 'source_dn': 'BTS-A', 'adj_ci': 303, 'adj_lac': 1, 'bcch_frequency': 60},
    ]
    payload = build_map_payload(sectors, edges, overshoot_km=50)
    by_pair = {(e['source_name'], e['target_name']): e for e in payload['edges']}
    assert by_pair[('CELL_A', 'CELL_B')]['bidirectional'] is True
    assert by_pair[('CELL_A', 'CELL_C')]['unidirectional'] is True
    assert by_pair[('CELL_A', 'CELL_B')]['co_channel'] is True


@patch('modules.adjacency_gis.logic.load_cells_2g_index', side_effect=_meta_index)
def test_ncl_overflow_flag(_mock_idx):
    sectors = [
        {'dn': 'BTS-A', 'bsc_id': '1', 'segment_name': 'CELL_A', 'cell_name': 'CELL_A',
         'cell_id': 101, 'bcch': 55, 'admin_state': '0'},
        {'dn': 'BTS-B', 'bsc_id': '1', 'segment_name': 'CELL_B', 'cell_name': 'CELL_B',
         'cell_id': 202, 'bcch': 70, 'admin_state': '0'},
    ]
    # 33 edges A→B (same target) — count is per source, not unique targets
    edges = [
        {'dn': f'ADCE-{i}', 'source_dn': 'BTS-A', 'adj_ci': 202, 'adj_lac': 1, 'bcch_frequency': 70}
        for i in range(33)
    ]
    payload = build_map_payload(sectors, edges, ncl_limit=32, overshoot_km=50)
    assert payload['counts']['ncl_overflow'] >= 1
    assert all(e['ncl_overflow'] for e in payload['edges'])


@patch('modules.adjacency_gis.logic.connect_metadata')
def test_build_bcch_map_payload_roles(mock_conn):
    """Selected BCCH red role; ±1 classified as lower/upper."""
    from modules.adjacency_gis.logic import build_bcch_map_payload

    class _Row(dict):
        def keys(self):
            return dict.keys(self)

    rows = [
        _Row(cell_name='A68', site_id='1', site_name='S1', vendor='Nokia',
             bcch=68, lat=31.95, lng=35.93, azimuth=0, frequency_band='GSM900'),
        _Row(cell_name='B67', site_id='2', site_name='S2', vendor='Nokia',
             bcch=67, lat=31.96, lng=35.94, azimuth=90, frequency_band='GSM900'),
        _Row(cell_name='C69', site_id='3', site_name='S3', vendor='Huawei',
             bcch=69, lat=31.97, lng=35.95, azimuth=180, frequency_band='GSM900'),
    ]
    cur = mock_conn.return_value
    cur.execute.return_value.fetchall.return_value = rows

    payload = build_bcch_map_payload(68)
    assert payload['selected'] == 68
    assert payload['lower'] == 67
    assert payload['upper'] == 69
    assert payload['counts'] == {'selected': 1, 'lower': 1, 'upper': 1}
    by_name = {c['cell_name']: c['role'] for c in payload['cells']}
    assert by_name == {'A68': 'selected', 'B67': 'lower', 'C69': 'upper'}
