"""Unit tests for WNCELG site split aggregation (no live NetAct)."""

from __future__ import annotations

from modules.configuration_dashboard.wncelg_logic import (
    STATUS_NO_SPLIT,
    STATUS_SPLIT,
    aggregate_site_groups,
    build_summary,
    enrich_wncelg_row,
    filter_sites_by_area,
    filter_sites_by_status,
    instance_from_dn,
    site_id_from_dn,
)


def test_site_id_and_instance_from_dn() -> None:
    dn = 'PLMN-PLMN/MRBTS-51021/WNBTS-1/WNCELG-2'
    assert site_id_from_dn(dn) == '51021'
    assert instance_from_dn(dn) == '2'
    assert site_id_from_dn('') == ''


def test_aggregate_one_group_is_no_split() -> None:
    rows = [
        {
            'DN': 'PLMN-PLMN/MRBTS-1/WNBTS-1/WNCELG-1',
            '$instance': '1',
            'site_id': '1',
            'site_name': 'Site1',
            'area': 'East Amman',
        },
    ]
    sites = aggregate_site_groups(rows)
    assert len(sites) == 1
    assert sites[0]['group_count'] == 1
    assert sites[0]['status'] == STATUS_NO_SPLIT


def test_aggregate_two_groups_is_split() -> None:
    rows = [
        {
            'DN': 'PLMN-PLMN/MRBTS-9/WNBTS-1/WNCELG-1',
            '$instance': '1',
            'site_id': '9',
            'site_name': 'SplitSite',
            'area': 'West Amman',
        },
        {
            'DN': 'PLMN-PLMN/MRBTS-9/WNBTS-1/WNCELG-2',
            '$instance': '2',
            'site_id': '9',
            'site_name': 'SplitSite',
            'area': 'West Amman',
        },
    ]
    sites = aggregate_site_groups(rows)
    assert len(sites) == 1
    assert sites[0]['group_count'] == 2
    assert sites[0]['status'] == STATUS_SPLIT
    assert sites[0]['instances'] == ['1', '2']


def test_build_summary_and_filters() -> None:
    sites = [
        {
            'site_id': '1',
            'area': 'East Amman',
            'status': STATUS_SPLIT,
            'group_count': 2,
        },
        {
            'site_id': '2',
            'area': 'West Amman',
            'status': STATUS_NO_SPLIT,
            'group_count': 1,
        },
        {
            'site_id': '3',
            'area': 'East Amman',
            'status': STATUS_NO_SPLIT,
            'group_count': 1,
        },
    ]
    summary = build_summary(sites)
    assert summary['total_sites'] == 3
    assert summary['split'] == 1
    assert summary['no_split'] == 2

    east = filter_sites_by_area(sites, 'East Amman')
    assert len(east) == 2
    only_split = filter_sites_by_status(sites, 'split')
    assert len(only_split) == 1
    assert only_split[0]['site_id'] == '1'


def test_enrich_wncelg_row_parses_dn() -> None:
    row = enrich_wncelg_row(
        {'DN': 'PLMN-PLMN/MRBTS-42/WNBTS-1/WNCELG-3'},
        site_lookup={
            '42': {
                'area': 'Irbid',
                'site_name': 'IRB42',
                'metadata_site_id': '42',
            },
        },
    )
    assert row['site_id'] == '42'
    assert row['$instance'] == '3'
    assert row['area'] == 'Irbid'
    assert row['site_name'] == 'IRB42'


def test_build_sankey_area_status_groups() -> None:
    from modules.configuration_dashboard.wncelg_logic import build_sankey_payload, group_count_label

    assert group_count_label(1) == '1 group'
    assert group_count_label(2) == '2 groups'
    assert group_count_label(5) == '3+ groups'

    sites = [
        {'area': 'East Amman', 'status': 'split', 'group_count': 2},
        {'area': 'East Amman', 'status': 'no_split', 'group_count': 1},
        {'area': 'West Amman', 'status': 'split', 'group_count': 3},
    ]
    payload = build_sankey_payload(sites, network_view=False, show_status=True)
    assert payload['summary']['total_sites'] == 3
    assert payload['summary']['split'] == 2
    assert payload['summary']['no_split'] == 1
    kinds = {n['name']: n['kind'] for n in payload['nodes']}
    assert kinds.get('East Amman') == 'area'
    assert kinds.get('Split') == 'status'
    assert kinds.get('2 groups') == 'groups'
    assert kinds.get('3+ groups') == 'groups'
    assert payload['links']

    network = build_sankey_payload(sites, network_view=True, show_status=True)
    assert network['summary']['areas'] == 0
    assert any(n['kind'] == 'status' for n in network['nodes'])
    assert not any(n['kind'] == 'area' for n in network['nodes'])
