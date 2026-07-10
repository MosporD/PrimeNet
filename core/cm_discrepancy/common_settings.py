"""Network-consensus ("common settings") computation for one MO class.

The golden reference is the mode (most frequent value) of each parameter
across every object instance in the network. Objects whose audited values
deviate from the common value are *mismatched*.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from core.cm_discrepancy.records import IDENTITY_COLUMNS, normalize_value

MAX_DISTRIBUTION_VALUES = 12


def is_identity_column(name: str) -> bool:
    return str(name).strip().lower() in IDENTITY_COLUMNS


def parameter_distributions(
    records: dict[str, dict[str, Any]],
    *,
    include_empty: bool = False,
) -> dict[str, Counter]:
    """Per-parameter value histogram across all object instances."""
    distributions: dict[str, Counter] = {}
    for record in records.values():
        for parameter, raw in record.items():
            if is_identity_column(parameter):
                continue
            value = normalize_value(raw)
            if not value and not include_empty:
                continue
            distributions.setdefault(str(parameter), Counter())[value] += 1
    return distributions


def common_value(counter: Counter) -> str:
    """Mode with a deterministic tie-break (highest count, then value text)."""
    if not counter:
        return ''
    best = max(counter.items(), key=lambda item: (item[1], item[0]))
    return best[0]


def distribution_text(counter: Counter, *, limit: int = MAX_DISTRIBUTION_VALUES) -> str:
    parts = [
        f'{value if value != "" else "(empty)"}: {count}'
        for value, count in counter.most_common(limit)
    ]
    if len(counter) > limit:
        parts.append(f'... +{len(counter) - limit} more value(s)')
    return ', '.join(parts)


def audit_mo_records(
    records: dict[str, dict[str, Any]],
    *,
    include_empty: bool = False,
) -> dict[str, Any]:
    """
    Compute Master/Summary rows and per-object mismatches for one MO class.

    Returns::

        {
          'master':   [{parameter, distribution, common_setting, unique_count,
                        total_samples, mismatch_count}, ...],
          'summary':  [{parameter, mismatch_count}, ...]   # mismatched params only
          'mismatched_objects': {object_key: [{parameter, value, common}, ...]},
        }
    """
    distributions = parameter_distributions(records, include_empty=include_empty)
    commons = {param: common_value(counter) for param, counter in distributions.items()}

    mismatched_objects: dict[str, list[dict[str, str]]] = {}
    mismatch_counts: dict[str, int] = {param: 0 for param in distributions}
    for object_key, record in records.items():
        deviations: list[dict[str, str]] = []
        for parameter, raw in record.items():
            param = str(parameter)
            if param not in commons:
                continue
            value = normalize_value(raw)
            if not value and not include_empty:
                continue
            if value != commons[param]:
                mismatch_counts[param] += 1
                deviations.append({
                    'parameter': param,
                    'value': value,
                    'common': commons[param],
                })
        if deviations:
            mismatched_objects[object_key] = deviations

    master = [
        {
            'parameter': param,
            'distribution': distribution_text(counter),
            'common_setting': commons[param],
            'unique_count': len(counter),
            'total_samples': sum(counter.values()),
            'mismatch_count': mismatch_counts.get(param, 0),
        }
        for param, counter in sorted(distributions.items(), key=lambda kv: kv[0].lower())
    ]
    summary = [
        {'parameter': row['parameter'], 'mismatch_count': row['mismatch_count']}
        for row in master
        if row['mismatch_count'] > 0
    ]
    return {
        'master': master,
        'summary': summary,
        'mismatched_objects': mismatched_objects,
    }
