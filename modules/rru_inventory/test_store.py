"""Tests for RMOD snapshot store + Excel export (no live NetAct)."""

from __future__ import annotations

import os
import tempfile

import modules.rru_inventory.store as store
from modules.rru_inventory.export import build_rmod_workbook
from modules.rru_inventory.logic import build_sankey_payload, snapshot_sankey_payload


def test_replace_and_load_snapshot(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, 'rmod_snapshot.db')
        monkeypatch.setattr(store, '_STORE_DIR', tmp)
        monkeypatch.setattr(store, '_STORE_DB', db_path)

        rows = [
            {
                'DN': 'PLMN-PLMN/MRBTS-1/EQM_R-1/RMOD_R-1',
                '$instance': '1',
                'site_id': '1',
                'metadata_site_id': '1',
                'site_name': 'Site1',
                'area': 'East Amman',
                'productName': 'RRU_A',
                'operationalState': 'enabled',
                'configDN': '',
                'techs': ['2G', '4G'],
                'unused': False,
                'multi_rat': True,
                'activeGsmCellsList': 'g1',
                'activeWcdmaCellsList': '',
                'activeLteCellsList': 'l1',
                'activeNrCellsList': '',
            },
            {
                'DN': 'PLMN-PLMN/MRBTS-2/EQM_R-1/RMOD_R-1',
                '$instance': '1',
                'site_id': '2',
                'site_name': 'Site2',
                'area': 'West Amman',
                'productName': 'RRU_B',
                'techs': ['Unused'],
                'unused': True,
                'multi_rat': False,
                'activeGsmCellsList': '',
                'activeWcdmaCellsList': '',
                'activeLteCellsList': '',
                'activeNrCellsList': '',
            },
        ]
        meta = store.replace_snapshot(
            rows,
            mo_class='com.nokia.srbts.eqmr:RMOD_R',
            summary={'physical_rrus': 2},
            trigger_source='manual',
        )
        assert meta['row_count'] == 2
        assert meta['status'] == 'ok'
        assert store.has_snapshot() is True

        east = store.load_rows(area='East Amman')
        assert len(east) == 1
        assert east[0]['productName'] == 'RRU_A'
        assert east[0]['techs'] == ['2G', '4G']

        # Avoid live metadata remap in this unit test.
        monkeypatch.setattr(
            'modules.rru_inventory.logic.apply_band_techs',
            lambda rows, band_index=None: list(rows),
        )
        payload = snapshot_sankey_payload(area='East Amman')
        assert payload['sankey']['summary']['physical_rrus'] == 1
        assert payload['meta']['row_count'] == 2
        assert payload['network_view'] is False

        network = snapshot_sankey_payload(area='')
        assert network['network_view'] is True
        assert network['sankey']['summary']['areas'] == 0

        assert store.list_snapshot_areas()
        areas = store.list_snapshot_areas()
        names = {a['area'] for a in areas}
        assert 'East Amman' in names
        assert 'West Amman' in names


def test_excel_export_bytes() -> None:
    rows = [
        {
            'area': 'East Amman',
            'site_id': '1',
            'site_name': 'Site1',
            'productName': 'RRU_A',
            'techs': ['4G'],
            'unused': False,
            'multi_rat': False,
            'operationalState': 'enabled',
            'activeGsmCellsList': '',
            'activeWcdmaCellsList': '',
            'activeLteCellsList': 'L1',
            'activeNrCellsList': '',
            'DN': 'DN-1',
            '$instance': '1',
            'configDN': '',
        }
    ]
    buf, filename = build_rmod_workbook({
        'rows': rows,
        'area': 'East Amman',
        'username': 'tester',
        'built_at': '2026-09-17T01:00:00+00:00',
        'mo_class': 'com.nokia.srbts.eqmr:RMOD_R',
        'summary': build_sankey_payload(rows)['summary'],
    })
    assert filename.startswith('Radio_Hardware_Inventory_')
    assert filename.endswith('.xlsx')
    assert buf.getvalue()[:2] == b'PK'
