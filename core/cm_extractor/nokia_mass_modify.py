"""Nokia CM Provision_Mass_Modification — parameter updates without SFTP file upload."""

from __future__ import annotations

import time
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


def is_empty_plan_error(message: str) -> bool:
    lower = (message or '').lower()
    return 'plan generated' in lower and 'empty' in lower


def _parameter_attempts(parameter: str, new_value: str, old_value: str = '') -> list[str]:
    """Build parameterValuesByNames attempts (new-only first for planned CM writes)."""
    attempts = [_parameter_values_expr(parameter, new_value, '')]
    if old_value and old_value != new_value:
        with_old = _parameter_values_expr(parameter, new_value, old_value)
        if with_old not in attempts:
            attempts.append(with_old)
    return attempts


def _wait_for_operations(
    client: NokiaOperationsClient,
    operations: list[dict[str, Any]],
    *,
    timeout_sec: int,
) -> None:
    """Poll NetAct until every started operation reaches a terminal state."""
    pending = {
        str(entry['operation_id']): entry
        for entry in operations
        if entry.get('operation_id')
    }
    if not pending:
        return

    deadline = time.time() + max(30, timeout_sec)
    last_status = 'STARTED'
    while pending and time.time() < deadline:
        statuses = client.get_statuses(list(pending.keys()))
        for item in statuses:
            op_id = str(item.get('operationId') or item.get('operation_id') or '').strip()
            if not op_id or op_id not in pending:
                continue
            last_status = str(item.get('status') or last_status)
            if last_status not in client.TERMINAL_STATUSES:
                continue
            entry = pending.pop(op_id)
            feedbacks = client.get_feedbacks(op_id)
            entry['status'] = last_status
            entry['feedbacks'] = feedbacks[:20]
            if last_status != 'FINISHED':
                dist_name = entry.get('dist_name') or op_id
                param_expr = entry.get('parameter_values') or entry.get('parameter') or ''
                raise NokiaOperationsError(
                    f'Mass modification failed for {dist_name} ({param_expr}): '
                    f'{_failure_detail(feedbacks)}',
                    payload={'operation_id': op_id, 'feedbacks': feedbacks[:20]},
                )
        if pending:
            time.sleep(client.poll_interval_sec)

    if pending:
        raise NokiaOperationsError(
            f'CM Operations timed out after {timeout_sec}s waiting for '
            f'{len(pending)} modification(s) (last status: {last_status}).',
        )


def apply_mass_modifications(
    updates: list[dict[str, Any]],
    *,
    wait: bool = True,
    mo_class: str = _DEFAULT_MO_CLASS,
    operation_timeout_sec: int = 900,
    client: NokiaOperationsClient | None = None,
) -> dict[str, Any]:
    """
    Apply CM parameter changes via Provision_Mass_Modification.

    Each update dict: dist_name/dn, parameter (default angle), value/new_value, optional old_value.
    """
    if not updates:
        raise ValueError('No parameter updates provided')

    client = client or build_nokia_operations_client()
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

        param_expr = _parameter_attempts(parameter, new_value, old_value)[0]
        op_id = client.start_operation(
            _OPERATION_NAME,
            operation_alias=f'PrimeNet mass modify {parameter}',
            attributes={
                'DN': dist_name,
                'objectClass': class_id,
                'parameterValuesByNames': param_expr,
            },
        )
        operations.append({
            'operation_id': op_id,
            'dist_name': dist_name,
            'mo_class': class_id,
            'parameter': parameter,
            'new_value': new_value,
            'parameter_values': param_expr,
        })

    if wait and operations:
        _wait_for_operations(client, operations, timeout_sec=operation_timeout_sec)

    return {
        'operation_name': _OPERATION_NAME,
        'change_count': len(operations),
        'operations': operations,
    }
