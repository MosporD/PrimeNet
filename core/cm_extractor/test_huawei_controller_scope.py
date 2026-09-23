"""Huawei CM extractor RNC/BSC scope mapping and MO filtering."""

from core.cm_extractor.huawei_semantics import mo_matches_huawei_scope
from core.cm_extractor.site_catalog import (
    HUAWEI_SCOPE_LEVELS,
    match_huawei_controller_ne_name,
    normalize_huawei_scope_level,
)


CATALOG = [
    {'ne_name': 'RNC01', 'product_name': 'BSC6900 UMTS'},
    {'ne_name': 'RNC11', 'product_name': 'BSC6910 UMTS'},
    {'ne_name': 'BSC_HQ_01', 'product_name': 'BSC6900 GSM'},
    {'ne_name': 'BSC_HQ_04', 'product_name': 'BSC6900 GSM'},
    {'ne_name': 'BSC_HQ_02', 'product_name': 'GBTS'},
    {'ne_name': '1004-Zawahrah_2_PE_EBand_TASC', 'product_name': 'BTS3900'},
]


def test_normalize_huawei_scope_accepts_controllers():
    assert normalize_huawei_scope_level('rnc') == 'RNC'
    assert normalize_huawei_scope_level('BSC') == 'BSC'
    assert normalize_huawei_scope_level('') == 'ENODEB'
    assert HUAWEI_SCOPE_LEVELS == ('ENODEB', 'RNC', 'BSC')
    try:
        normalize_huawei_scope_level('MRBTS')
        raise AssertionError('expected ValueError')
    except ValueError:
        pass


def test_match_rnc_by_numeric_id():
    assert match_huawei_controller_ne_name('1', '', CATALOG, scope_level='RNC') == 'RNC01'
    assert match_huawei_controller_ne_name('01', 'RNC01', CATALOG, scope_level='RNC') == 'RNC01'
    assert match_huawei_controller_ne_name('11', '', CATALOG, scope_level='RNC') == 'RNC11'


def test_match_rnc_does_not_confuse_rnc1_with_rnc11():
    assert match_huawei_controller_ne_name('1', '', CATALOG, scope_level='RNC') != 'RNC11'


def test_match_bsc_by_name_token():
    assert match_huawei_controller_ne_name('HQ_01', '', CATALOG, scope_level='BSC') == 'BSC_HQ_01'
    assert match_huawei_controller_ne_name('BSC_HQ_04', '', CATALOG, scope_level='BSC') == 'BSC_HQ_04'


def test_match_bsc_ignores_gbts_with_bsc_prefix():
    assert match_huawei_controller_ne_name('HQ_02', '', CATALOG, scope_level='BSC') == ''


def test_match_skips_enodeb_names():
    assert match_huawei_controller_ne_name('1004', '1004-Zawahrah', CATALOG, scope_level='RNC') == ''


def test_mo_scope_filter():
    cell = {'id': 'CELL', 'technology': '4G', 'products': ['BTS3900']}
    ucell = {'id': 'UCELL', 'technology': '3G', 'products': ['BSC6900 UMTS']}
    gcell = {'id': 'GCELL', 'technology': '2G', 'products': ['BSC6900 GSM']}
    assert mo_matches_huawei_scope(cell, 'ENODEB')
    assert not mo_matches_huawei_scope(ucell, 'ENODEB')
    assert mo_matches_huawei_scope(ucell, 'RNC')
    assert not mo_matches_huawei_scope(gcell, 'RNC')
    assert mo_matches_huawei_scope(gcell, 'BSC')
    assert not mo_matches_huawei_scope(cell, 'BSC')


def test_dictionary_mo_technology_and_high_cardinality():
    from core.cm_extractor.huawei_semantics import (
        MML_HIGH_CARDINALITY_CHUNK,
        MML_HIGH_CARDINALITY_NE_LIMIT,
        MML_SINGLE_NE_LIMIT,
        _mo_technology,
        is_high_cardinality_mo,
        mml_chunk_size_for_mo,
    )

    assert _mo_technology('CELL') == '4G'
    assert _mo_technology('EUTRANINTERFREQNCELL') == '4G'
    assert is_high_cardinality_mo('EutranInterFreqNcell')
    assert is_high_cardinality_mo('EUTRANINTERFREQNCELL')
    assert not is_high_cardinality_mo('CELL')
    assert mml_chunk_size_for_mo('EUTRANINTERFREQNCELL') == MML_HIGH_CARDINALITY_CHUNK
    assert mml_chunk_size_for_mo('CELL') == MML_SINGLE_NE_LIMIT
    assert MML_HIGH_CARDINALITY_NE_LIMIT == 40


def test_high_cardinality_ne_limit_raises():
    import core.cm_extractor.huawei_semantics as sem
    from core.cm_extractor.huawei_client import HuaweiCmClient

    class _StubClient(HuaweiCmClient):
        def __init__(self):
            pass

        def _record_skipped_mml_nes(self, ne_names, *, reason):
            return None

        def run_mml_chunked(self, command, ne_names, *, chunk_size=100, alternates_by_ne=None):
            raise AssertionError('should refuse before MML call')

        def consume_mml_errors(self):
            return []

    nes = [f'{1300 + i}-Site_{i}_TASC_O' for i in range(41)]
    original = sem._partition_ne_names_for_mo
    sem._partition_ne_names_for_mo = lambda names, mo_id: (list(names), [])
    try:
        sem._selection_rows(
            _StubClient(),
            nes,
            {'mo_id': 'EUTRANINTERFREQNCELL', 'export_all': True},
        )
        raise AssertionError('expected ValueError for oversized neighbor extract')
    except ValueError as exc:
        assert 'high-cardinality' in str(exc).lower()
        assert '40' in str(exc)
    finally:
        sem._partition_ne_names_for_mo = original
