"""Tests for NetAct ↔ PrimeNet metadata MRBTS site id mapping."""

from core.cm_extractor.site_catalog import resolve_nokia_metadata_site_id


def test_resolve_nokia_metadata_site_id_direct():
    known = {'801', '1201', '50801'}
    assert resolve_nokia_metadata_site_id('801', known_metadata_ids=known) == '801'
    assert resolve_nokia_metadata_site_id('1201', known_metadata_ids=known) == '1201'


def test_resolve_nokia_metadata_site_id_prefixed_netact():
    known = {'801', '302', '1201'}
    assert resolve_nokia_metadata_site_id('50801', known_metadata_ids=known) == '801'
    # 2302 absent from known → fall back to shorter suffix 302
    assert resolve_nokia_metadata_site_id('52302', known_metadata_ids=known) == '302'


def test_resolve_nokia_metadata_site_id_prefers_longest_suffix():
    """53308 must map to 3308, not the shorter suffix 308."""
    known = {'308', '3308', '801', '2302', '302', '1301', '1001', '1201'}
    assert resolve_nokia_metadata_site_id('53308', known_metadata_ids=known) == '3308'
    assert resolve_nokia_metadata_site_id('50308', known_metadata_ids=known) == '308'
    assert resolve_nokia_metadata_site_id('52302', known_metadata_ids=known) == '2302'
    assert resolve_nokia_metadata_site_id('51301', known_metadata_ids=known) == '1301'
    assert resolve_nokia_metadata_site_id('51001', known_metadata_ids=known) == '1001'
    assert resolve_nokia_metadata_site_id('61201', known_metadata_ids=known) == '1201'


def test_resolve_nokia_metadata_site_id_unknown_prefix_falls_back():
    known = {'1201'}
    assert resolve_nokia_metadata_site_id('51001', known_metadata_ids=known) == '51001'
