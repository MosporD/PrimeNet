"""Tests for the RET hologram site geometry (sector grouping from metadata)."""

import sqlite3

import pytest

from modules.ret_management import site_layout
from modules.ret_management.site_layout import (
    _build_sectors,
    _fill_missing_azimuths,
    default_beamwidth,
    fetch_site_layout,
    normalize_azimuth,
    normalize_sector_key,
    sector_label,
    site_id_candidates,
)


def test_normalize_sector_key_maps_letters_to_numbers():
    assert normalize_sector_key('A') == '1'
    assert normalize_sector_key('c') == '3'
    assert normalize_sector_key('Sector 3') == '3'
    assert normalize_sector_key('2.0') == '2'
    assert normalize_sector_key('') == ''


def test_normalize_sector_key_from_cell_name_suffix():
    assert normalize_sector_key('', cell_name='AMMAN1_B2') == '2'
    assert normalize_sector_key('', cell_name='AMMAN1-C') == '3'


def test_normalize_sector_key_ignores_tech_suffix_letters():
    """``_N1`` is an NR cell and ``_G1`` a GSM cell — neither names a sector."""
    assert normalize_sector_key('', cell_name='AMMAN1_N1') == ''
    assert normalize_sector_key('', cell_name='AMMAN1_G1') == ''


def test_normalize_azimuth_wraps_into_range():
    assert normalize_azimuth('370.5') == 10.5
    assert normalize_azimuth('-10') == 350.0
    assert normalize_azimuth('abc') is None
    assert normalize_azimuth('') is None


def test_sector_label_adds_letter_alias():
    assert sector_label('1') == '1 (A)'
    assert sector_label('3') == '3 (C)'
    assert sector_label('AZ30') == 'AZ30'
    assert sector_label('') == 'Unassigned'


def test_default_beamwidth_by_sector_count():
    assert default_beamwidth(1) == 360.0
    assert default_beamwidth(3) == 65.0
    assert default_beamwidth(6) < 65.0


def _cell(sector, azimuth, *, tech='4G-FDD', etilt=4.0, height=25.0, name='C', band='L18'):
    return {
        'cell_name': name,
        'technology': tech,
        'sector_key': sector,
        'sector_raw': sector,
        'azimuth': azimuth,
        'electrical_tilt': etilt,
        'mechanical_tilt': 2.0,
        'height': height,
        'band': band,
        'vendor': 'Nokia',
        'latitude': None,
        'longitude': None,
        'state': '',
        'site_ref': '1021',
        'site_ref_name': 'SITE',
    }


def test_build_sectors_groups_and_averages_azimuth():
    sectors, warnings = _build_sectors([
        _cell('1', 30.0, name='A1'),
        _cell('1', 32.0, tech='2G', band='GSM 900', name='G1'),
        _cell('2', 150.0, name='B1'),
    ])
    assert [s['key'] for s in sectors] == ['1', '2']
    assert sectors[0]['azimuth'] == pytest.approx(31.0, abs=0.1)
    assert sectors[0]['technologies'] == ['2G', '4G-FDD']
    assert sectors[0]['cell_count'] == 2
    assert not warnings


def test_build_sectors_folds_sectorless_cell_onto_matching_azimuth():
    sectors, warnings = _build_sectors([
        _cell('1', 30.0, name='A1'),
        _cell('', 31.0, tech='5G', band='100MHz', name='N1'),
    ])
    assert [s['key'] for s in sectors] == ['1']
    assert sectors[0]['cell_count'] == 2
    assert sectors[0]['technologies'] == ['4G-FDD', '5G']
    assert 'matched onto a sector by azimuth' in warnings[0]


def test_build_sectors_buckets_sectorless_cell_with_no_azimuth_match():
    sectors, _warnings = _build_sectors([
        _cell('1', 30.0, name='A1'),
        _cell('', 200.0, name='X1'),
    ])
    assert 'AZ200' in [s['key'] for s in sectors]


def test_build_sectors_warns_and_estimates_missing_azimuth():
    sectors, warnings = _build_sectors([
        _cell('1', 30.0, name='A1'),
        _cell('2', None, name='B1'),
    ])
    assert any('No azimuth in metadata' in w for w in warnings)
    _fill_missing_azimuths(sectors)
    estimated = [s for s in sectors if s['azimuth_source'] == 'estimated']
    assert estimated and estimated[0]['azimuth'] is not None


def test_site_id_candidates_includes_metadata_and_raw_ids(monkeypatch):
    monkeypatch.setattr(site_layout, '_known_nokia_metadata_site_ids', lambda: {'1021'})
    candidates = site_id_candidates('nokia', '51021', metadata_site_id='1021')
    assert '1021' in candidates
    assert '51021' in candidates


def test_site_id_candidates_survives_missing_metadata(monkeypatch):
    def boom():
        raise RuntimeError('metadata not synced')

    monkeypatch.setattr(site_layout, '_known_nokia_metadata_site_ids', boom)
    assert site_id_candidates('nokia', '51021') == ['51021']


@pytest.fixture
def metadata_db(tmp_path, monkeypatch):
    path = tmp_path / 'metadata.db'
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE sites (site_id TEXT PRIMARY KEY, site_name TEXT, latitude REAL, '
        'longitude REAL, region TEXT, site_type TEXT, vendor TEXT, status TEXT)'
    )
    conn.execute(
        "INSERT INTO sites VALUES ('1021','AMMAN_TEST',31.95,35.93,'Central','Rooftop','Nokia','Active')"
    )
    conn.execute(
        'CREATE TABLE cells_4g_fdd (cell_name TEXT, vendor TEXT, enb_name TEXT, '
        'enb_id_actual TEXT, sector TEXT, azimuth REAL, etilt REAL, mtilt REAL, '
        'height REAL, band TEXT, lat REAL, long REAL, active_state TEXT)'
    )
    conn.executemany(
        'INSERT INTO cells_4g_fdd VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [
            ('AMMAN_TEST_A1', 'Nokia', 'AMMAN_TEST', '1021', '1', 30, 4, 2, 25, 'L18', 31.95, 35.93, 'Unlocked'),
            ('AMMAN_TEST_B1', 'Nokia', 'AMMAN_TEST', '1021', '2', 150, 3, 2, 25, 'L18', 31.95, 35.93, 'Unlocked'),
            ('AMMAN_TEST_C1', 'Nokia', 'AMMAN_TEST', '1021', '3', 270, 6, 2, 25, 'L18', 31.95, 35.93, 'Unlocked'),
        ],
    )
    conn.commit()

    def fake_connect():
        new = sqlite3.connect(path)
        new.row_factory = sqlite3.Row
        return new

    monkeypatch.setattr(site_layout, 'connect_metadata', fake_connect)
    monkeypatch.setattr(site_layout, '_known_nokia_metadata_site_ids', lambda: {'1021'})
    yield path
    conn.close()


def test_fetch_site_layout_reads_three_sectors(metadata_db):
    layout = fetch_site_layout('nokia', site_id='51021', metadata_site_id='1021')
    assert layout['site']['site_name'] == 'AMMAN_TEST'
    assert layout['site']['antenna_height'] == 25.0
    assert layout['sector_count'] == 3
    assert [s['azimuth'] for s in layout['sectors']] == [30.0, 150.0, 270.0]
    assert [s['label'] for s in layout['sectors']] == ['1 (A)', '2 (B)', '3 (C)']
    assert layout['warnings'] == []


def test_fetch_site_layout_warns_for_unknown_site(metadata_db):
    layout = fetch_site_layout('nokia', site_id='59999')
    assert layout['sector_count'] == 0
    assert any('No inventory rows found' in w for w in layout['warnings'])


def test_fetch_site_layout_requires_an_identifier(metadata_db):
    with pytest.raises(ValueError, match='site_id or site_name'):
        fetch_site_layout('nokia', site_id='')


def test_fetch_site_layout_rejects_unknown_vendor(metadata_db):
    with pytest.raises(ValueError, match='nokia or huawei'):
        fetch_site_layout('ericsson', site_id='1021')
