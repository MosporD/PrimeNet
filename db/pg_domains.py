"""Postgres domain catalog for the Postgres-only runtime.

Require:

  NCM_DATABASE_URL=postgresql://…

``NCM_PG_DOMAINS`` unset enables every group. A subset still works for
narrow cutovers, but catalogued ``open_db`` paths with no mapped schema
fail closed (no SQLite fallback).

``NCM_APP_DATABASE_URL`` alone still means **app schema only** (legacy).
Nokia and Huawei hourly tables share names like ``"4G_Hourly"``, so each
logical store maps to its own Postgres schema.
"""

from __future__ import annotations

import os

ALL_GROUPS = (
    'app',
    'metadata',
    'neighbors',
    'groups',
    'balance',
    'pm',
    'femto',
    'son_ml',
    'nh_precalc',
    'kpi_headers',
    'cm',
    'elevation',
    'rru',
    'adjacency',
    'wncelg',
    'cases',
    'pm_plus',
    'marketing',
)

# Group (env value) → Postgres schema names (1:1 with canonical store paths).
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
    'femto': ('femto_pm', 'femto_user_kpis'),
    'son_ml': ('son_ml',),
    'nh_precalc': ('nh_precalc',),
    'kpi_headers': ('kpi_headers',),
    'cm': ('cm_snapshots',),
    'elevation': ('elevation',),
    'rru': ('rru_inventory',),
    'adjacency': ('adjacency_gis',),
    'wncelg': ('wncelg',),
    'cases': ('cases',),
    'pm_plus': ('pm_plus',),
    'marketing': ('marketing',),
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


def require_postgres_url() -> str:
    """Return the Postgres URL or raise. PrimeNet is Postgres-only."""
    url = postgres_url()
    if not url_is_postgres(url):
        raise RuntimeError(
            'NCM_DATABASE_URL is required (Postgres-only runtime). '
            'Laptop: set NCM_APP_POSTGRES_PASSWORD in .env, then '
            '`docker compose --profile app-db up -d postgres`, then set '
            'NCM_DATABASE_URL=postgresql://primenet:<password>@127.0.0.1:5432/primenet'
        )
    return url


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
        ADJACENCY_GIS_DB,
        CM_SNAPSHOTS_DB,
        ELEVATION_DB,
        FEMTO_PM_DB,
        FEMTO_USER_KPI_DB,
        HUAWEI_GROUPS_DAILY_DB,
        HUAWEI_GROUPS_DB,
        HUAWEI_NEIGHBOR_RAW_DB,
        HUAWEI_PM_DAILY_DB,
        HUAWEI_PM_DB,
        KPI_HEADERS_DB,
        MARKETING_DB,
        METADATA_DB,
        NCMUSERS_DB,
        NEIGHBOR_KPI_DB,
        NETWORK_BALANCE_DB,
        NH_PRECALC_DB,
        NOKIA_GROUPS_DAILY_DB,
        NOKIA_GROUPS_DB,
        NOKIA_PM_DAILY_DB,
        NOKIA_PM_DB,
        OPTIMIZATION_CASES_DB,
        PM_PLUS_DB,
        RRU_INVENTORY_DB,
        SON_ML_DB,
        WNCELG_SNAPSHOT_DB,
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
        'femto_pm': FEMTO_PM_DB,
        'femto_user_kpis': FEMTO_USER_KPI_DB,
        'son_ml': SON_ML_DB,
        'nh_precalc': NH_PRECALC_DB,
        'kpi_headers': KPI_HEADERS_DB,
        'cm_snapshots': CM_SNAPSHOTS_DB,
        'elevation': ELEVATION_DB,
        'rru_inventory': RRU_INVENTORY_DB,
        'adjacency_gis': ADJACENCY_GIS_DB,
        'wncelg': WNCELG_SNAPSHOT_DB,
        'cases': OPTIMIZATION_CASES_DB,
        'pm_plus': PM_PLUS_DB,
        'marketing': MARKETING_DB,
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
