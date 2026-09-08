"""Copy ``ncm_users.db`` (SQLite) into Postgres schema ``app``.

Requires ``NCM_APP_DATABASE_URL``. Does not touch PM/metadata SQLite files.

  python scripts/migrate_ncm_users_to_postgres.py
  python scripts/migrate_ncm_users_to_postgres.py --replace

Default refuses to load if Postgres ``users`` already has rows.
``--replace`` truncates app schema tables then copies again.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('NCM_SKIP_ACTIVATION', '1')
os.environ.setdefault('NCM_DISABLE_SCHEDULER', '1')
os.environ.setdefault('NCM_DISABLE_LIVE_LOGGER_TERMINAL', '1')

from database_enhanced import init_db  # noqa: E402
from db.runtime import connect_app, execute_query, is_app_postgresql, table_columns  # noqa: E402
from sync_config import NCMUSERS_DB  # noqa: E402

# Parent tables first so FKs succeed even if replication_role is not used.
COPY_ORDER = [
    'users',
    'sessions',
    'activity_log',
    'tasks',
    'task_updates',
    'filter_profiles',
    'config_versions',
    'report_archive',
    'user_preferences',
    'saved_views',
    'user_vendor_credentials',
    'feature_access',
    'sync_log',
    'performance_reports',
    'profile_photo_requests',
    'elevation_cache',
    'config_scheduler_tasks',
    'config_scheduler_task_files',
    'config_scheduler_result_files',
    'cm_extractor_jobs',
    'cm_extractor_job_runs',
    'cm_extractor_job_notifications',
]


def _sqlite_tables(path: str) -> dict[str, list[str]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        out: dict[str, list[str]] = {}
        for t in names:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
            out[t] = cols
        return out
    finally:
        conn.close()


def _pg_user_count(conn) -> int:
    row = execute_query(conn, 'SELECT COUNT(*) AS n FROM users').fetchone()
    if isinstance(row, dict):
        return int(row.get('n') or 0)
    return int(row[0] or 0)


def _copy_table(sqlite_path: str, pg, table: str, columns: list[str]) -> int:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
    finally:
        src.close()
    if not rows:
        return 0
    pg_cols = table_columns(pg, table)
    use_cols = [c for c in columns if c in pg_cols]
    if not use_cols:
        print(f'  skip {table}: no overlapping columns')
        return 0
    placeholders = ', '.join('?' for _ in use_cols)
    col_sql = ', '.join(f'"{c}"' for c in use_cols)
    sql = f'INSERT INTO {table} ({col_sql}) VALUES ({placeholders})'
    n = 0
    for row in rows:
        vals = [row[c] for c in use_cols]
        execute_query(pg, sql, vals)
        n += 1
    return n


def _reset_identities(pg, tables: list[str]) -> None:
    for table in tables:
        cols = table_columns(pg, table)
        if 'id' not in cols:
            continue
        try:
            execute_query(
                pg,
                f"""
                SELECT setval(
                    pg_get_serial_sequence('app.{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    true
                )
                """,
            )
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate ncm_users.db to Postgres app schema')
    parser.add_argument('--replace', action='store_true', help='Truncate Postgres app tables first')
    args = parser.parse_args()

    if not is_app_postgresql():
        print('Set NCM_APP_DATABASE_URL to a postgresql:// URL first.')
        return 2
    if not os.path.isfile(NCMUSERS_DB):
        print(f'SQLite app DB not found: {NCMUSERS_DB}')
        return 2

    print(f'Source: {NCMUSERS_DB}')
    print('Target: NCM_APP_DATABASE_URL (schema app)')
    init_db()
    pg = connect_app()
    try:
        existing = _pg_user_count(pg)
        if existing and not args.replace:
            print(f'Postgres users already has {existing} row(s). Pass --replace to overwrite.')
            return 3
        if args.replace:
            execute_query(pg, 'SET session_replication_role = replica')
            for table in reversed(COPY_ORDER):
                try:
                    execute_query(pg, f'TRUNCATE TABLE {table} CASCADE')
                except Exception:
                    pass
            pg.commit()

        sqlite_meta = _sqlite_tables(NCMUSERS_DB)
        execute_query(pg, 'SET session_replication_role = replica')
        copied = 0
        for table in COPY_ORDER:
            if table not in sqlite_meta:
                continue
            n = _copy_table(NCMUSERS_DB, pg, table, sqlite_meta[table])
            print(f'  {table}: {n} rows')
            copied += n
        _reset_identities(pg, COPY_ORDER)
        execute_query(pg, 'SET session_replication_role = DEFAULT')
        pg.commit()
        print(f'Done. Copied {copied} rows. SQLite file is unchanged (cold backup).')
        print('Keep NCM_APP_DATABASE_URL set on the server. Unset it to fall back to SQLite.')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    raise SystemExit(main())
