"""Unit tests for Nokia RMOD_R Sankey aggregation (no live NetAct)."""

from __future__ import annotations

from modules.rru_inventory.logic import (
    UNKNOWN_PRODUCT,
    UNUSED_TECH,
    build_sankey_payload,
    enrich_rmod_row,
    filter_rows_by_area,
    is_cells_list_empty,
    product_name_for_row,
    resolve_nokia_rmod_mo_class,
    site_id_from_dn,
    techs_for_rmod,
)


def test_is_cells_list_empty_common_shapes() -> None:
    assert is_cells_list_empty(None) is True
    assert is_cells_list_empty('') is True
    assert is_cells_list_empty('   ') is True
    assert is_cells_list_empty('[]') is True
    assert is_cells_list_empty('[ ]') is True
    assert is_cells_list_empty({}) is True
    assert is_cells_list_empty([]) is True
    assert is_cells_list_empty(['', '  ']) is True
    assert is_cells_list_empty('null') is True
    assert is_cells_list_empty('-') is True

    assert is_cells_list_empty('LNCEL-1') is False
    assert is_cells_list_empty('LNCEL-1,LNCEL-2') is False
    assert is_cells_list_empty(['LNCEL-1']) is False
    assert is_cells_list_empty({'values': ['LNCEL-1']}) is False


def test_techs_for_rmod_single_multi_unused() -> None:
    assert techs_for_rmod({
        'activeGsmCellsList': 'BTS-1',
        'activeWcdmaCellsList': '',
        'activeLteCellsList': '[]',
        'activeNrCellsList': None,
    }) == ['2G']

    assert techs_for_rmod({
        'activeGsmCellsList': 'G1',
        'activeWcdmaCellsList': 'W1',
        'activeLteCellsList': 'L1',
        'activeNrCellsList': 'N1',
    }) == ['2G', '3G', '4G', '5G']

    assert techs_for_rmod({
        'activeGsmCellsList': '',
        'activeWcdmaCellsList': '[]',
        'activeLteCellsList': None,
        'activeNrCellsList': [],
    }) == [UNUSED_TECH]


def test_product_name_unknown() -> None:
    assert product_name_for_row({'productName': 'AHFIA'}) == 'AHFIA'
    assert product_name_for_row({'productName': ''}) == UNKNOWN_PRODUCT
    assert product_name_for_row({}) == UNKNOWN_PRODUCT


def test_site_id_from_dn() -> None:
    assert site_id_from_dn(
        'PLMN-PLMN/MRBTS-51021/EQM_R-1/APEQM_R-1/RMOD_R-1'
    ) == '51021'
    assert site_id_from_dn('') == ''


def test_sankey_multi_rat_fan_out_weights() -> None:
    rows = [
        enrich_rmod_row({
            'DN': 'PLMN-PLMN/MRBTS-1/EQM_R-1/RMOD_R-1',
            'productName': 'RRU_A',
            'activeGsmCellsList': 'g1',
            'activeLteCellsList': 'l1',
            'activeWcdmaCellsList': '',
            'activeNrCellsList': '',
        }, site_lookup={'1': {'area': 'East Amman', 'site_name': 'Site1', 'metadata_site_id': '1'}}),
        enrich_rmod_row({
            'DN': 'PLMN-PLMN/MRBTS-1/EQM_R-1/RMOD_R-2',
            'productName': 'RRU_B',
            'activeGsmCellsList': '',
            'activeLteCellsList': '',
            'activeWcdmaCellsList': '',
            'activeNrCellsList': '',
        }, site_lookup={'1': {'area': 'East Amman', 'site_name': 'Site1', 'metadata_site_id': '1'}}),
    ]

    assert rows[0]['techs'] == ['2G', '4G']
    assert rows[0]['multi_rat'] is True
    assert rows[1]['unused'] is True

    payload = build_sankey_payload(rows)
    assert payload['summary']['physical_rrus'] == 2
    assert payload['summary']['unused'] == 1
    assert payload['summary']['multi_rat'] == 1
    assert payload['summary']['by_tech']['2G'] == 1
    assert payload['summary']['by_tech']['4G'] == 1
    assert payload['summary']['by_tech']['Unused'] == 1

    # Area→2G, Area→4G, Area→Unused, then tech→product links.
    area_to_tech = {
        (link['source_id'], link['target_id']): link['value']
        for link in payload['links']
        if link['source_id'] == 'East Amman'
    }
    assert area_to_tech[('East Amman', '2G')] == 1
    assert area_to_tech[('East Amman', '4G')] == 1
    assert area_to_tech[('East Amman', 'Unused')] == 1

    tech_to_rru = {
        (link['source_id'], link['target_id']): link['value']
        for link in payload['links']
        if link['source_id'] in ('2G', '4G', 'Unused')
    }
    assert tech_to_rru[('2G', 'RRU_A')] == 1
    assert tech_to_rru[('4G', 'RRU_A')] == 1
    assert tech_to_rru[('Unused', 'RRU_B')] == 1


def test_filter_rows_by_area() -> None:
    rows = [
        {'area': 'East Amman', 'productName': 'A'},
        {'area': 'West Amman', 'productName': 'B'},
    ]
    assert len(filter_rows_by_area(rows, 'East Amman')) == 1
    assert len(filter_rows_by_area(rows, 'all')) == 2
    assert len(filter_rows_by_area(rows, '')) == 2


def test_resolve_mo_class_fallback_without_client() -> None:
    assert resolve_nokia_rmod_mo_class(None) == 'com.nokia.srbts.eqmr:RMOD_R'


def test_record_from_managed_object_list_params() -> None:
    from modules.rru_inventory.logic import record_from_managed_object, techs_for_rmod

    unused = record_from_managed_object({
        'moId': 'PLMN-PLMN/MRBTS-1/EQM_R-1/RMOD_R-1',
        'parameters': {
            'productName': 'AHFIA',
            'activeGsmCellsList': [],
            'activeWcdmaCellsList': {'items': []},
            'activeLteCellsList': None,
            'activeNrCellsList': [],
            'operationalState': 'enabled',
        },
    })
    assert unused['productName'] == 'AHFIA'
    assert techs_for_rmod(unused) == [UNUSED_TECH]

    multi = record_from_managed_object({
        'moId': 'PLMN-PLMN/MRBTS-1/EQM_R-1/RMOD_R-2',
        'parameters': {
            'productName': 'AHLOA',
            'activeGsmCellsList': ['BTS-1'],
            'activeLteCellsList': {'items': [{'dn': 'LNCEL-1'}, {'dn': 'LNCEL-2'}]},
            'activeWcdmaCellsList': [],
            'activeNrCellsList': [],
        },
    })
    assert techs_for_rmod(multi) == ['2G', '4G']


def test_managed_list_empty_shapes() -> None:
    from modules.rru_inventory.logic import managed_list_to_cells_value

    assert is_cells_list_empty(managed_list_to_cells_value([])) is True
    assert is_cells_list_empty(managed_list_to_cells_value({'items': []})) is True
    assert is_cells_list_empty(managed_list_to_cells_value(['LNCEL-1'])) is False
    assert is_cells_list_empty(managed_list_to_cells_value({'items': [{'dn': 'x'}]})) is False
