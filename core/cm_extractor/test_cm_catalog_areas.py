"""CM picker area labels must use the canonical site_area resolver."""

from core.cm_extractor.site_catalog import (
    areas_from_site_items,
    canonical_cm_area,
    nokia_mrbts_area_for_site,
)
from core.radio.cm_live import _area_key


def test_canonical_cm_area_manual_override():
    assert canonical_cm_area('6086', fallback='', index={}) == 'South Jordan'
    assert canonical_cm_area('9999', fallback='West Amman', index={}) == 'South Amman'


def test_canonical_cm_area_aliases_when_cluster_unknown():
    assert canonical_cm_area('6600', fallback='North', index={}) == 'North Jordan'
    assert canonical_cm_area('6600', fallback='Zarqa', index={}) == 'East Jordan'


def test_canonical_cm_area_cluster_map():
    assert canonical_cm_area('1001', fallback='Zarqa', index={}) == 'East Jordan'
    assert canonical_cm_area('101', fallback='South Amman', index={}) == 'South Amman'


def test_nokia_mrbts_area_manual_and_alias():
    _meta, area, cluster = nokia_mrbts_area_for_site(
        '6086',
        known_metadata_ids={'6086'},
        clusters={},
        cluster_to_area={},
        area_map={},
        site_area_index={},
    )
    assert _meta == '6086'
    assert area == 'South Jordan'
    assert cluster == ''

    _meta, area, cluster = nokia_mrbts_area_for_site(
        '6600',
        known_metadata_ids={'6600'},
        clusters={'6600': '66'},
        cluster_to_area={'66': 'North'},
        area_map={'6600': {'area': 'North', 'cluster': '66'}},
        site_area_index={},
    )
    assert area == 'North Jordan'
    assert cluster == '66'


def test_nokia_mrbts_area_maps_prefixed_netact_id():
    _meta, area, _cluster = nokia_mrbts_area_for_site(
        '50801',
        known_metadata_ids={'801'},
        clusters={'801': '8'},
        cluster_to_area={'8': 'South Jordan'},
        area_map={'801': {'area': 'South Jordan', 'cluster': '8'}},
        site_area_index={},
    )
    assert _meta == '801'
    assert area == 'South Jordan'


def test_areas_from_site_items_counts_canonical_names():
    items = [
        {'area': 'North Jordan'},
        {'area': 'North Jordan'},
        {'area': 'East Jordan'},
        {'area': ''},
    ]
    rows = areas_from_site_items(items)
    assert rows[0] == {'area': 'North Jordan', 'site_count': 2}
    assert rows[1] == {'area': 'East Jordan', 'site_count': 1}


def test_live_area_filter_accepts_raw_or_canonical():
    assert _area_key('North') == _area_key('North Jordan')
    assert _area_key('Zarqa') == _area_key('East Jordan')
    assert _area_key('west amman') == 'west amman'
