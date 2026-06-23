"""
Static KPI catalog by vendor/technology for the Performance UI.

The catalog is sourced from sync_config column maps to keep one source of truth.
"""

from sync_config import NOKIA_PM_COLUMN_MAPS, HUAWEI_PM_COLUMN_MAPS


_SKIP_KEYS = {'cell_name', 'timestamp'}


def _cols_from_map(col_map: dict) -> list[str]:
    vals = []
    seen = set()
    for k, v in (col_map or {}).items():
        if k in _SKIP_KEYS:
            continue
        name = str(v or '').strip()
        if not name:
            continue
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        vals.append(name)
    return vals


def build_kpi_headers_map() -> dict:
    mapping = {}
    for tech, col_map in NOKIA_PM_COLUMN_MAPS.items():
        mapping[f'Nokia|{tech}'] = _cols_from_map(col_map)
    for tech, col_map in HUAWEI_PM_COLUMN_MAPS.items():
        mapping[f'Huawei|{tech}'] = _cols_from_map(col_map)
    return mapping


KPI_HEADERS_MAP = build_kpi_headers_map()

