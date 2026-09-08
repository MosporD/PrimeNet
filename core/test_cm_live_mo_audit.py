"""Entire-MO parameter audit helpers (no live CM)."""

from core.radio.cm_live import (
    _build_mo_parameter_summaries,
    _is_entire_mo_request,
    _is_identity_column,
    _non_scalar_param_from_error,
    _parameter_names_from_records,
)
from modules.cm_parameter_audit.export import build_audit_workbook
from modules.cm_parameter_audit.routes import _slim_audit_payload


def test_entire_mo_tokens():
    assert _is_entire_mo_request('', True) is True
    assert _is_entire_mo_request('*', False) is True
    assert _is_entire_mo_request('ALL', False) is True
    assert _is_entire_mo_request('pci', False) is False


def test_identity_columns_skipped():
    assert _is_identity_column('DN') is True
    assert _is_identity_column('$instance') is True
    assert _is_identity_column('pci') is False
    assert _is_identity_column('earfcnDL') is False


def test_non_scalar_param_from_nokia_error():
    message = (
        'Nokia CM API error (400): InvalidArgumentException: invalid MOPath: '
        '/ NetActCommon:PLMN / MRBTS / NOKLTE:LNBTS as $lnbts -> ( dn() , '
        '@hpsRampUpArpPrioLev, @immciAtTauS1RelCauses, @maxNumNrCell ) '
        'caused by MOQException: expr: @immciAtTauS1RelCauses caused by '
        'MOQParameterException: parameter: ParameterValue( immciAtTauS1RelCauses, null ), '
        'scalar value required'
    )
    assert _non_scalar_param_from_error(message) == 'immciAtTauS1RelCauses'
    assert _non_scalar_param_from_error('unrelated failure') == ''


def test_parameter_names_prefer_metadata_order():
    records = {
        'a': {'DN': 'x', 'pci': '1', 'earfcnDL': '1650', 'qRxLevMin': '-120'},
        'b': {'DN': 'y', 'pci': '2', 'earfcnDL': '1650', 'qRxLevMin': '-120'},
    }
    names = _parameter_names_from_records(records, preferred=['qRxLevMin', 'pci', 'missing'])
    assert names[:2] == ['qRxLevMin', 'pci']
    assert 'earfcnDL' in names
    assert 'DN' not in names
    assert 'missing' not in names


def test_mo_summaries_flag_inconsistent_parameter():
    objects = [
        {'ne': 'A', 'object': '1', 'values': {'pci': '1', 'tac': '100'}},
        {'ne': 'B', 'object': '2', 'values': {'pci': '2', 'tac': '100'}},
        {'ne': 'C', 'object': '3', 'values': {'pci': '1', 'tac': '100'}},
    ]
    summaries, empty = _build_mo_parameter_summaries(objects, ['pci', 'tac', 'emptyParam'])
    by_name = {item['parameter']: item for item in summaries}
    assert empty == ['emptyParam']
    assert by_name['tac']['status'] == 'consistent'
    assert by_name['pci']['distinct_values'] == 2
    assert by_name['pci']['inconsistent_count'] == 1
    assert summaries[0]['parameter'] == 'pci'


def test_mo_workbook_and_slim_payload():
    payload = {
        'audit_mode': 'mo',
        'vendor': 'nokia',
        'mo_class': 'NOKLTE:LNCEL',
        'scope_level': 'MRBTS',
        'query_mode': 'network_wide',
        'summary': {
            'object_count': 2,
            'ne_count': 2,
            'parameter_count': 1,
            'inconsistent_parameter_count': 1,
            'status': 'high',
        },
        'parameter_summaries': [
            {
                'parameter': 'pci',
                'distinct_values': 2,
                'most_common_value': '1',
                'most_common_count': 1,
                'inconsistent_count': 1,
                'inconsistency_pct': 50.0,
                'status': 'high',
                'value_distribution': [{'value': '1', 'count': 1, 'percent': 50}],
                'value_distribution_all': [
                    {'value': '1', 'count': 1, 'percent': 50},
                    {'value': '2', 'count': 1, 'percent': 50},
                ],
            }
        ],
        'object_matrix': [
            {
                'ne': 'Site-1',
                'site_id': '1',
                'area': 'West Amman',
                'cell_name': 'LNCEL-1',
                'dn': 'PLMN/MRBTS-1/LNCEL-1',
                'values': {'pci': '1'},
            },
            {
                'ne': 'Site-2',
                'site_id': '2',
                'area': 'West Amman',
                'cell_name': 'LNCEL-1',
                'dn': 'PLMN/MRBTS-2/LNCEL-1',
                'values': {'pci': '2'},
            },
        ],
        'warnings': [],
    }
    workbook, filename = build_audit_workbook(payload)
    assert filename.endswith('.xlsx')
    assert 'fullMO' in filename
    assert workbook.getvalue()[:2] == b'PK'

    slim = _slim_audit_payload(payload)
    assert 'object_matrix' not in slim
    assert slim['parameter_summaries'][0].get('value_distribution_all') is None


if __name__ == "__main__":
    import sys

    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, exc)
    sys.exit(1 if failed else 0)
