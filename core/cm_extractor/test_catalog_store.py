"""Tests for CM catalog path resolution (shared Docker volume)."""

from __future__ import annotations


from core.cm_extractor.catalog_store import cm_catalog_path, cm_catalog_read_candidates


def test_cm_catalog_path_uses_ncm_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv('NCM_DATA_ROOT', str(tmp_path))
    # sync_config caches DATA_ROOT at import — force re-read via getenv path in helper
    import sync_config

    monkeypatch.setattr(sync_config, 'DATA_ROOT', str(tmp_path))
    path = cm_catalog_path('nokia_netact_inventory.json')
    assert path == tmp_path / 'var' / 'cm_catalogs' / 'nokia_netact_inventory.json'


def test_cm_catalog_read_candidates_include_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv('NCM_DATA_ROOT', str(tmp_path))
    import sync_config

    monkeypatch.setattr(sync_config, 'DATA_ROOT', str(tmp_path))
    candidates = cm_catalog_read_candidates('nokia_netact_inventory.json')
    assert candidates[0] == tmp_path / 'var' / 'cm_catalogs' / 'nokia_netact_inventory.json'
    assert any(c.name == 'nokia_netact_inventory.json' and 'data' in c.parts for c in candidates[1:])
