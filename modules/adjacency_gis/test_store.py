"""Store round-trip for Adjacency GIS multi-vendor snapshot."""

from __future__ import annotations

import os

import modules.adjacency_gis.store as store


def test_replace_and_load_snapshot(tmp_path, monkeypatch):
    db = tmp_path / 'adjacency_snapshot.db'
    monkeypatch.setattr(store, '_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(store, '_STORE_DB', str(db))

    sectors = [{
        'dn': 'BTS-1',
        'bsc_id': '10',
        'bcf_id': '1',
        'instance': '1',
        'segment_name': 'CELL_A',
        'cell_name': 'CELL_A',
        'cell_id': 101,
        'bcch': 55,
        'trx_dn': 'BTS-1/TRX-1',
        'admin_state': 'unlocked',
    }]
    edges = [{
        'dn': 'ADCE-1',
        'bts_dn': 'BTS-1',
        'adj_ci': 202,
        'adj_lac': 1,
        'adj_mcc': 416,
        'adj_mnc': 1,
        'bcch_frequency': 60,
    }]
    meta = store.replace_snapshot(
        sectors,
        edges,
        warnings=['note'],
        summary={'sectors': 1},
        build_seconds=1.2,
        trigger_source='test',
        vendor='nokia',
    )
    assert meta['sector_count'] == 1
    assert meta['edge_count'] == 1
    assert os.path.isfile(str(db))
    loaded_s = store.load_sectors('nokia')
    loaded_e = store.load_edges('nokia')
    assert loaded_s[0]['cell_name'] == 'CELL_A'
    assert loaded_e[0]['adj_ci'] == 202
    assert store.list_bsc_ids('nokia') == ['10']
    again = store.get_build_meta('nokia')
    assert again['warnings'] == ['note']


def test_vendor_snapshots_independent(tmp_path, monkeypatch):
    db = tmp_path / 'adjacency_snapshot.db'
    monkeypatch.setattr(store, '_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(store, '_STORE_DB', str(db))

    store.replace_vendor_snapshot(
        'nokia',
        [{'dn': 'N1', 'bsc_id': 'N', 'segment_name': 'A', 'cell_name': 'A', 'cell_id': 1, 'bcch': 1}],
        [{'dn': 'NE1', 'bts_dn': 'N1', 'adj_ci': 2}],
    )
    store.replace_vendor_snapshot(
        'huawei',
        [{'dn': 'H1', 'bsc_id': 'H', 'segment_name': 'B', 'cell_name': 'B', 'cell_id': 3, 'bcch': 5}],
        [{'dn': 'HE1', 'bts_dn': 'H1', 'adj_ci': 4}],
    )
    assert len(store.load_sectors('nokia')) == 1
    assert len(store.load_sectors('huawei')) == 1
    assert len(store.load_sectors()) == 2
    combined = store.get_build_meta()
    assert combined['sector_count'] == 2
    assert combined['edge_count'] == 2
    assert 'nokia' in combined['by_vendor']
    assert 'huawei' in combined['by_vendor']

    # Replacing nokia must not wipe huawei
    store.replace_vendor_snapshot('nokia', [], [])
    assert len(store.load_sectors('huawei')) == 1
    assert len(store.load_sectors('nokia')) == 0
