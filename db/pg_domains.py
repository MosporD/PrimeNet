"""Postgres domain catalog for the phased SQLite → Postgres cutover.

Default remains SQLite. Enable domains with:

  NCM_DATABASE_URL=postgresql://…
  NCM_PG_DOMAINS=app,metadata,neighbors,groups,balance,pm

``NCM_APP_DATABASE_URL`` alone still means **app schema only** (phase 1).
``NCM_DATABASE_URL`` with ``NCM_PG_DOMAINS`` unset enables every group.

Nokia and Huawei hourly tables share names like ``"4G_Hourly"``, so each
SQLite file maps to its own Postgres schema — never a shared ``pm`` search_path.
"""

from __future__ import annotations

import os

ALL_GROUPS = ('app', 'metadata', 'neighbors', 'groups', 'balance', 'pm')

# Group (env value) → Postgres schema names (1:1 with canonical SQLite files).
DOMAIN_GROUPS: dict[str, tuple[str, ...]] = {
    'app': ('app',),
    'metadata': ('metadata',),
    'neighbors': ('neighbors_nokia', 'neighbors_huawei'),
    'groups': (
        'groups_nokia_hourly',
        'groups_huawei_hourly',
        'groups_nokia_daily',
        'groups_huawei_daily',
    ),
    'balance': ('balance',),
    'pm': (
        'pm_nokia_hourly',
        'pm_huawei_hourly',
        'pm_nokia_daily',
        'pm_huawei_daily',
    ),
}


def postgres_url() -> str:
    return (
        os.getenv('NCM_DATABASE_URL')
        or os.getenv('NCM_APP_DATABASE_URL')
        or os.getenv('APP_DATABASE_URL')
        or ''
    ).strip()


def url_is_postgres(url: str | None = None) -> bool:
    u = (url if url is not None else postgres_url()).lower()
    return u.startswith('postgres://') or u.startswith('postgresql://')


def enabled_groups() -> frozenset[str]:
    if not url_is_postgres():
        return frozenset()
    raw = (os.getenv('NCM_PG_DOMAINS') or '').strip()
    database_url_set = bool((os.getenv('NCM_DATABASE_URL') or '').strip())
    if not raw:
        if database_url_set:
            return frozenset(ALL_GROUPS)
        return frozenset({'app'})
    parts = {p.strip().lower() for p in raw.split(',') if p.strip()}
    return frozenset(p for p in parts if p in ALL_GROUPS)


def enabled_schemas() -> frozenset[str]:
    out: set[str] = set()
    groups = enabled_groups()
    for group, schemas in DOMAIN_GROUPS.items():
        if group in groups:
            out.update(schemas)
    return frozenset(out)


def is_domain_postgresql(name: str) -> bool:
    """True if *name* is an enabled group (``pm``) or schema (``pm_nokia_hourly``)."""
    key = (name or '').strip().lower()
    groups = enabled_groups()
    if key in groups:
        return True
    return key in enabled_schemas()


def canonical_sqlite_paths() -> dict[str, str]:
    from sync_config import (
        HUAWEI_GROUPS_DAILY_DB,
        HUAWEI_GROUPS_DB,
        HUAWEI_NEIGHBOR_RAW_DB,
        HUAWEI_PM_DAILY_DB,
        HUAWEI_PM_DB,
        METADATA_DB,
        NCMUSERS_DB,
        NEIGHBOR_KPI_DB,
        NETWORK_BALANCE_DB,
        NOKIA_GROUPS_DAILY_DB,
        NOKIA_GROUPS_DB,
        NOKIA_PM_DAILY_DB,
        NOKIA_PM_DB,
    )

    return {
        'app': NCMUSERS_DB,
        'metadata': METADATA_DB,
        'pm_nokia_hourly': NOKIA_PM_DB,
        'pm_huawei_hourly': HUAWEI_PM_DB,
        'pm_nokia_daily': NOKIA_PM_DAILY_DB,
        'pm_huawei_daily': HUAWEI_PM_DAILY_DB,
        'groups_nokia_hourly': NOKIA_GROUPS_DB,
        'groups_huawei_hourly': HUAWEI_GROUPS_DB,
        'groups_nokia_daily': NOKIA_GROUPS_DAILY_DB,
        'groups_huawei_daily': HUAWEI_GROUPS_DAILY_DB,
        'neighbors_nokia': NEIGHBOR_KPI_DB,
        'neighbors_huawei': HUAWEI_NEIGHBOR_RAW_DB,
        'balance': NETWORK_BALANCE_DB,
    }


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def schema_for_sqlite_path(path: str | None) -> str | None:
    """Return the Postgres schema if this canonical file is on Postgres; else None."""
    if not path:
        return None
    enabled = enabled_schemas()
    if not enabled:
        return None
    try:
        want = _norm_path(path)
    except (OSError, TypeError, ValueError):
        return None
    for schema, sqlite_path in canonical_sqlite_paths().items():
        if schema not in enabled:
            continue
        try:
            if _norm_path(sqlite_path) == want:
                return schema
        except (OSError, TypeError, ValueError):
            continue
    return None


def pm_schema(vendor: str, scope: str = 'hourly') -> str:
    v = 'huawei' if str(vendor or '').strip().lower().startswith('huawei') else 'nokia'
    s = 'daily' if str(scope or 'hourly').strip().lower() in ('d', 'day', 'daily') else 'hourly'
    return f'pm_{v}_{s}'


def attach_alias_for_schema(schema: str, *, dual_vendor: bool) -> str:
    """SQLite ATTACH alias, or the Postgres schema name (same ``alias.\"table\"`` SQL)."""
    if not dual_vendor:
        return schema
    mapping = {
        'pm_nokia_hourly': 'nokia_pm',
        'pm_nokia_daily': 'nokia_pm',
        'pm_huawei_hourly': 'huawei_pm',
        'pm_huawei_daily': 'huawei_pm',
    }
    return mapping.get(schema, schema)
