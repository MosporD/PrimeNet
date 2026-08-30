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
