"""Copy every enabled SQLite domain into Postgres, in dependency order.

  NCM_DATABASE_URL=postgresql://…
  NCM_PG_DOMAINS=app,metadata,neighbors,groups,balance,pm
  python scripts/migrate_all_sqlite_to_postgres.py

App DB uses ``migrate_ncm_users_to_postgres.py`` (runs ``init_db`` first).
Other domains use ``migrate_sqlite_domain_to_postgres.py``.

Does not run against a live server from this script's defaults — the URL
must already be set. SQLite files are left in place as a cold backup.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('NCM_SKIP_ACTIVATION', '1')
os.environ.setdefault('NCM_DISABLE_SCHEDULER', '1')
os.environ.setdefault('NCM_DISABLE_LIVE_LOGGER_TERMINAL', '1')

from db.pg_domains import ALL_GROUPS, canonical_sqlite_paths, enabled_groups, enabled_schemas  # noqa: E402

# Copy order: app first, metadata before PM seeders, then the rest.
_SCHEMA_ORDER = [
    'app',
    'metadata',
    'neighbors_nokia',
    'neighbors_huawei',
    'groups_nokia_hourly',
    'groups_huawei_hourly',
    'groups_nokia_daily',
    'groups_huawei_daily',
    'balance',
    'pm_nokia_hourly',
    'pm_huawei_hourly',
    'pm_nokia_daily',
    'pm_huawei_daily',
]


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate all enabled SQLite domains to Postgres')
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--chunk', type=int, default=5000)
    parser.add_argument(
        '--skip-app',
        action='store_true',
        help='Skip ncm_users (use if app was already migrated)',
    )
    args = parser.parse_args()

    groups = enabled_groups()
    if not groups:
        print('No Postgres domains enabled. Set NCM_DATABASE_URL and NCM_PG_DOMAINS.')
        print(f'Groups: {", ".join(ALL_GROUPS)}')
        return 2

    print(f'Enabled groups: {", ".join(sorted(groups))}')
    schemas = enabled_schemas()
    rc = 0
    here = os.path.dirname(os.path.abspath(__file__))

    if 'app' in groups and not args.skip_app:
        print('\n=== app ===')
        cmd = [sys.executable, os.path.join(here, 'migrate_ncm_users_to_postgres.py')]
        if args.replace:
            cmd.append('--replace')
        code = subprocess.call(cmd)
        if code:
            return code

    from scripts.migrate_sqlite_domain_to_postgres import migrate_schema

    paths = canonical_sqlite_paths()
    for schema in _SCHEMA_ORDER:
        if schema == 'app':
            continue
        if schema not in schemas:
            continue
        sqlite_path = paths[schema]
        if not os.path.isfile(sqlite_path):
            print(f'\n=== {schema} === skipped (no SQLite file)')
            continue
        print(f'\n=== {schema} ===')
        code = migrate_schema(schema, replace=args.replace, chunk=max(100, args.chunk))
        if code:
            print(f'{schema} failed with code {code}')
            rc = code
            break
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
