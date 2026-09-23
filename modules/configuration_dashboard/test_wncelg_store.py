"""Tests for WNCELG snapshot store + Excel export (no live NetAct)."""

from __future__ import annotations

import os
import tempfile

import modules.configuration_dashboard.wncelg_store as store
from modules.configuration_dashboard.export import build_wncelg_workbook
from modules.configuration_dashboard.wncelg_logic import (
    STATUS_NO_SPLIT,
    STATUS_SPLIT,
    aggregate_site_groups,
    build_summary,
    snapshot_sites_payload,
)


def test_replace_and_load_wncelg_snapshot(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, 'wncelg_snapshot.db')
        monkeypatch.setattr(store, '_STORE_DIR', tmp)
        monkeypatch.setattr(store, '_STORE_DB', db_path)

        group_rows = [
            {
                'DN': 'PLMN-PLMN/MRBTS-1/WNBTS-1/WNCELG-1',
                '$instance': '1',
                'site_id': '1',
                'metadata_site_id': '1',
                'site_name': 'Site1',
                'area': 'East Amman',
            },
            {
                'DN': 'PLMN-PLMN/MRBTS-1/WNBTS-1/WNCELG-2',
                '$instance': '2',
                'site_id': '1',
                'metadata_site_id': '1',
                'site_name': 'Site1',
                'area': 'East Amman',
            },
            {
                'DN': 'PLMN-PLMN/MRBTS-2/WNBTS-1/WNCELG-1',
                '$instance': '1',
                'site_id': '2',
                'site_name': 'Site2',
                'area': 'West Amman',
            },
        ]
        site_rows = aggregate_site_groups(group_rows)
        summary = build_summary(site_rows)
        meta = store.replace_snapshot(
            group_rows,
            site_rows,
            mo_class='com.nokia.srbts.wcdma:WNCELG',
            summary=summary,
            trigger_source='manual',
        )
        assert meta['group_count'] == 3
        assert meta['site_count'] == 2
        assert meta['status'] == 'ok'
        assert store.has_snapshot() is True

        sites = store.load_sites()
        assert len(sites) == 2
        by_id = {s['site_id']: s for s in sites}
        assert by_id['1']['status'] == STATUS_SPLIT
        assert by_id['1']['group_count'] == 2
        assert by_id['2']['status'] == STATUS_NO_SPLIT

        areas = store.list_snapshot_areas()
        assert any(a['area'] == 'East Amman' and a['split_count'] == 1 for a in areas)

        payload = snapshot_sites_payload(area='East Amman', status='split')
        assert len(payload['sites']) == 1
        assert payload['sites'][0]['site_id'] == '1'
        assert payload['summary']['split'] == 1


def test_wncelg_excel_export() -> None:
    sites = [
        {
            'area': 'East Amman',
            'site_id': '1',
            'site_name': 'Site1',
            'status': STATUS_SPLIT,
            'group_count': 2,
            'instances': ['1', '2'],
            'dns': [
                'PLMN-PLMN/MRBTS-1/WNBTS-1/WNCELG-1',
                'PLMN-PLMN/MRBTS-1/WNBTS-1/WNCELG-2',
            ],
            'metadata_site_id': '1',
        },
    ]
    buf, filename = build_wncelg_workbook({
        'sites': sites,
        'area': 'East Amman',
        'status': 'split',
        'username': 'tester',
        'built_at': '2026-09-20T00:00:00+00:00',
        'mo_class': 'com.nokia.srbts.wcdma:WNCELG',
        'summary': {'total_sites': 1, 'split': 1, 'no_split': 0},
    })
    assert filename.startswith('WNCELG_Site_Split_')
    assert buf.getvalue()[:2] == b'PK'
