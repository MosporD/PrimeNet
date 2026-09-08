"""Phase 0 — inventory every SQLite file PrimeNet still uses.

Prints canonical paths, extra stores, table counts, and which domain is in
scope for the Postgres cutover. App DB (ncm_users) is phase 1; everything
else stays SQLite until a later phase.

Does not open Postgres. Safe to run on this laptop without a server.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (  # noqa: E402
    DATABASES_ROOT,
    DATA_ROOT,
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    HUAWEI_NEIGHBOR_RAW_DB,
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    KPI_HEADERS_DB,
    METADATA_DB,
    NCMUSERS_DB,
    NEIGHBOR_KPI_DB,
    NETWORK_BALANCE_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
)

# Domain → Postgres phase. Plumbing is opt-in via NCM_DATABASE_URL / NCM_PG_DOMAINS.
CATALOG: list[tuple[str, str, str, str]] = [
    # label, path, domain, phase
    ('ncm_users (app)', NCMUSERS_DB, 'app', '1 — NCM_APP_DATABASE_URL or group app'),
    ('metadata', METADATA_DB, 'metadata', '2 — group metadata'),
    ('nokia PM hourly', NOKIA_PM_DB, 'pm', '4 — group pm (schema pm_nokia_hourly)'),
    ('huawei PM hourly', HUAWEI_PM_DB, 'pm', '4 — group pm (schema pm_huawei_hourly)'),
    ('nokia PM daily', NOKIA_PM_DAILY_DB, 'pm', '4 — group pm (schema pm_nokia_daily)'),
    ('huawei PM daily', HUAWEI_PM_DAILY_DB, 'pm', '4 — group pm (schema pm_huawei_daily)'),
    ('nokia groups hourly', NOKIA_GROUPS_DB, 'groups', '3 — group groups'),
    ('huawei groups hourly', HUAWEI_GROUPS_DB, 'groups', '3 — group groups'),
    ('nokia groups daily', NOKIA_GROUPS_DAILY_DB, 'groups', '3 — group groups'),
    ('huawei groups daily', HUAWEI_GROUPS_DAILY_DB, 'groups', '3 — group groups'),
    ('nokia neighbor KPIs', NEIGHBOR_KPI_DB, 'neighbors', '3 — group neighbors'),
    ('huawei neighbor raw', HUAWEI_NEIGHBOR_RAW_DB, 'neighbors', '3 — group neighbors'),
    ('network balance', NETWORK_BALANCE_DB, 'balance', '3 — group balance'),
    ('KPI headers', KPI_HEADERS_DB, 'catalog', 'keep SQLite'),
]

EXTRA: list[tuple[str, str, str, str]] = [
    (
        'femto PM',
        os.path.join(DATABASES_ROOT, 'cells', 'femto_pm_cells.db'),
        'femto',
        'keep SQLite',
    ),
    (
        'femto user KPIs',
        os.path.join(DATABASES_ROOT, 'cells', 'femto_user_kpis.db'),
        'femto',
        'keep SQLite',
    ),
    (
        'elevation cache',
        os.path.join(DATABASES_ROOT, 'geo', 'elevation_cache.db'),
        'geo',
        'keep SQLite',
    ),
    (
        'CM snapshots',
        os.path.join(DATABASES_ROOT, 'radio', 'cm_snapshots.db'),
        'cm',
        'keep SQLite',
    ),
    (
        'SON ML store',
        os.path.join(DATABASES_ROOT, 'son_analytics', 'ml.db'),
        'son',
        'keep SQLite',
    ),
    (
        'Network Health precalc',
        os.path.join(DATABASES_ROOT, 'network_health', 'precalc.db'),
        'nh',
        'keep SQLite',
    ),
]

CONNECT_BYPASS = (
    'Unmapped files (femto, SON ML, KPI headers, CM snapshots) always stay SQLite. '
    'Canonical PM/metadata/neighbors/groups/balance go through db.runtime.open_db.'
)


def _size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return '—'
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f} KB'
    if n < 1024 * 1024 * 1024:
        return f'{n / (1024 * 1024):.1f} MB'
    return f'{n / (1024 * 1024 * 1024):.2f} GB'


def _inspect(path: str, *, count_rows: bool) -> tuple[int, int, list[str]]:
    if not os.path.isfile(path):
        return -1, 0, []
    try:
        conn = sqlite3.connect(path, timeout=5)
    except sqlite3.Error:
        return -1, 0, []
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        total = 0
        if count_rows:
            for t in tables:
                try:
                    total += int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
                except sqlite3.Error:
                    pass
        else:
            total = -1
        return len(tables), total, tables
    finally:
        conn.close()


def _row(label: str, path: str, domain: str, phase: str) -> None:
    ntab, nrows, tables = _inspect(path, count_rows=(domain == 'app'))
    exists = os.path.isfile(path)
    print(f'  {label}')
    print(f'    domain={domain}  phase={phase}')
    print(f'    {path}')
    if not exists:
        print('    FILE MISSING')
        return
    if nrows < 0:
        print(f'    size={_size(path)}  tables={ntab}')
    else:
        print(f'    size={_size(path)}  tables={ntab}  rows={nrows:,}')
    if domain == 'app' and tables:
        print('    tables: ' + ', '.join(tables))


def main() -> int:
    print('PrimeNet SQLite inventory (phase 0)')
    print(f'DATA_ROOT={DATA_ROOT}')
    print()
    print('=== Canonical files (sync_config) ===')
    for item in CATALOG:
        _row(*item)
        print()
    print('=== Extra stores (not in sync_config constants) ===')
    for item in EXTRA:
        _row(*item)
        print()
    print('=== ATTACH / cross-store joins ===')
    print('  SQLite: performance_meta_pm_conn ATTACH PM files as pm / nokia_pm / huawei_pm')
    print('  Postgres: same helper uses schema-qualified aliases (pm_nokia_hourly, …).')
    print('  Enabling group pm requires group metadata (same backend).')
    print()
    print('=== connect_* routing ===')
    print('  db.runtime.open_db maps canonical SQLite paths to Postgres schemas')
    print('  when NCM_DATABASE_URL / NCM_PG_DOMAINS enable that group.')
    print()
    print(CONNECT_BYPASS)
    print()
    app_url = (os.getenv('NCM_APP_DATABASE_URL') or os.getenv('APP_DATABASE_URL') or '').strip()
    db_url = (os.getenv('NCM_DATABASE_URL') or '').strip()
    domains = (os.getenv('NCM_PG_DOMAINS') or '').strip()
    print('=== Postgres gate (opt-in; default SQLite) ===')
    print(f'  NCM_APP_DATABASE_URL set: {bool(app_url)}  (app schema only if DATABASE_URL unset)')
    print(f'  NCM_DATABASE_URL set: {bool(db_url)}')
    print(f'  NCM_PG_DOMAINS: {domains or "(unset → all groups if DATABASE_URL, else app-only)"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
