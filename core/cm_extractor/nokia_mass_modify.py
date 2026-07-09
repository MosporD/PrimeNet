"""Nokia CM Provision_Mass_Modification — parameter updates without SFTP file upload."""

from __future__ import annotations

from typing import Any

from core.cm_extractor.config import build_nokia_operations_client
from core.cm_extractor.nokia_operations_client import NokiaOperationsClient, NokiaOperationsError

_DEFAULT_MO_CLASS = 'NOKLTE:LNCEL'
_OPERATION_NAME = 'Provision_Mass_Modification'


def _parameter_values_expr(parameter: str, new_value: str, old_value: str = '') -> str:
    param = (parameter or '').strip()
    new_val = str(new_value if new_value is not None else '').strip()
    old_val = str(old_value or '').strip()
    if not param or not new_val:
        raise ValueError('Parameter and new value are required')
    if old_val and old_val != new_val:
        return f'{param}={old_val}:{new_val}'
    return f'{param}={new_val}'


def _failure_detail(feedbacks: list[dict[str, Any]]) -> str:
    for item in reversed(feedbacks or []):
        title = str(item.get('title') or '').strip()
        details = str(item.get('details') or '').strip()
        level = str(item.get('type') or '').strip().upper()
        if level in ('ERROR', 'WARNING') and (title or details):
            return details or title
    for item in reversed(feedbacks or []):
        title = str(item.get('title') or '').strip()
        if title:
            return title
    return 'CM Operations returned FAILED'


def apply_mass_modifications(
    updates: list[dict[str, Any]],
    *,
    wait: bool = True,
    mo_class: str = _DEFAULT_MO_CLASS,
    operation_timeout_sec: int = 900,
) -> dict[str, Any]:
    """
    Apply CM parameter changes via Provision_Mass_Modification.

    Each update dict: dist_name/dn, parameter (default angle), value/new_value, optional old_value.
    """
    if not updates:
        raise ValueError('No parameter updates provided')

    client = build_nokia_operations_client()
    operations: list[dict[str, Any]] = []

    for item in updates:
        dist_name = str(
            item.get('dist_name') or item.get('dn') or item.get('DN') or ''
        ).strip()
        parameter = str(item.get('parameter') or 'angle').strip()
        new_value = item.get('value')
        if new_value is None:
            new_value = item.get('new_value')
        if new_value is None and parameter == 'angle':
            new_value = item.get('angle')
        new_value = str(new_value if new_value is not None else '').strip()
        old_value = str(item.get('old_value') or item.get('old_angle') or '').strip()
        class_id = str(item.get('mo_class') or item.get('mo_class_id') or mo_class).strip()

        if not dist_name:
            raise ValueError('Each update requires dist_name (DN)')
        if not new_value:
            raise ValueError(f'Each update requires a value for {parameter}')

        param_expr = _parameter_values_expr(parameter, new_value, old_value)
        op_id = client.start_operation(
            _OPERATION_NAME,
            operation_alias=f'PrimeNet mass modify {parameter}',
            attributes={
                'DN': dist_name,
                'objectClass': class_id,
                'parameterValuesByNames': param_expr,
            },
        )
        entry: dict[str, Any] = {
            'operation_id': op_id,
            'dist_name': dist_name,
            'mo_class': class_id,
            'parameter': parameter,
            'new_value': new_value,
            'parameter_values': param_expr,
        }
        if wait:
            status, feedbacks = client.wait_for_operation(op_id, timeout_sec=operation_timeout_sec)
            entry['status'] = status
            entry['feedbacks'] = feedbacks[:20]
            if status != 'FINISHED':
                raise NokiaOperationsError(
                    f'Mass modification failed for {dist_name} ({param_expr}): '
                    f'{_failure_detail(feedbacks)}',
                    payload={'operation_id': op_id, 'feedbacks': feedbacks[:20]},
                )
        operations.append(entry)

    return {
        'operation_name': _OPERATION_NAME,
        'change_count': len(operations),
        'operations': operations,
    }
