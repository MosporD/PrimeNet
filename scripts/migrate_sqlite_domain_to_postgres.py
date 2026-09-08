"""Copy one canonical SQLite file into its Postgres schema.

  python scripts/migrate_sqlite_domain_to_postgres.py --schema metadata
  python scripts/migrate_sqlite_domain_to_postgres.py --schema pm_nokia_hourly --chunk 20000
  python scripts/migrate_sqlite_domain_to_postgres.py --schema metadata --replace

Does not delete the SQLite file (cold backup). Refuses to copy if the target
schema already has rows, unless ``--replace``.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('NCM_SKIP_ACTIVATION', '1')
os.environ.setdefault('NCM_DISABLE_SCHEDULER', '1')
os.environ.setdefault('NCM_DISABLE_LIVE_LOGGER_TERMINAL', '1')

from db.pg_domains import canonical_sqlite_paths, enabled_schemas, postgres_url  # noqa: E402
from db.runtime import execute_query, open_db, table_columns  # noqa: E402

_SKIP_TABLES = frozenset({'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'})


def _sqlite_objects(path: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    conn = sqlite3.connect(path)
    try:
        tables = [
            (r[0], r[1] or '')
            for r in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
            ).fetchall()
        ]
        indexes = [
            (r[0], r[1] or '')
            for r in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' "
                "AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        return tables, indexes
    finally:
        conn.close()


def _ensure_if_not_exists(ddl: str, kind: str) -> str:
    pattern = rf'CREATE\s+{kind}\s+(?!IF\s+NOT\s+EXISTS)'
    return re.sub(pattern, f'CREATE {kind} IF NOT EXISTS ', ddl, count=1, flags=re.IGNORECASE)


def _pg_has_rows(pg, table: str) -> bool:
    try:
        row = execute_query(pg, f'SELECT COUNT(*) AS n FROM "{table}" LIMIT 1').fetchone()
    except Exception:
        return False
    if row is None:
        return False
    if isinstance(row, dict):
        return int(row.get('n') or 0) > 0
    return int(row[0] or 0) > 0


def _copy_table(sqlite_path: str, pg, table: str, chunk: int) -> int:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    try:
        col_rows = src.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = [r[1] for r in col_rows]
        if not columns:
            return 0
        pg_cols = table_columns(pg, table)
        use_cols = [c for c in columns if c in pg_cols]
        if not use_cols:
            print(f'    skip {table}: no overlapping columns')
            return 0
        col_sql = ', '.join(f'"{c}"' for c in use_cols)
        placeholders = ', '.join('?' for _ in use_cols)
        insert_sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'
        cur = src.execute(f'SELECT {col_sql} FROM "{table}"')
        copied = 0
        while True:
            batch = cur.fetchmany(chunk)
            if not batch:
                break
            rows = [tuple(r[c] for c in use_cols) for r in batch]
            pg.executemany(insert_sql, rows)
            copied += len(rows)
            if copied % (chunk * 5) == 0:
                pg.commit()
                print(f'    {table}: {copied} rows…')
        return copied
    finally:
        src.close()


def migrate_schema(schema: str, *, replace: bool, chunk: int) -> int:
    paths = canonical_sqlite_paths()
    sqlite_path = paths.get(schema)
    if not sqlite_path:
        print(f'Unknown schema {schema!r}. Known: {", ".join(paths)}')
        return 2
    if schema not in enabled_schemas():
        print(
            f'Schema {schema} is not enabled. Set NCM_DATABASE_URL (or NCM_APP_DATABASE_URL '
            f'for app) and include its group in NCM_PG_DOMAINS.'
        )
        return 2
    if not os.path.isfile(sqlite_path):
        print(f'SQLite file not found: {sqlite_path}')
        return 2

    print(f'Source: {sqlite_path}')
    print(f'Target: schema {schema}')
    tables, indexes = _sqlite_objects(sqlite_path)
    pg = open_db(sqlite_path)
    try:
        if not replace:
            for name, _sql in tables:
                if name in _SKIP_TABLES:
                    continue
                if _pg_has_rows(pg, name):
                    print(
                        f'Postgres {schema}.{name} already has rows. Pass --replace to overwrite.'
                    )
                    return 3
        if replace:
            for name, _sql in reversed(tables):
                if name in _SKIP_TABLES:
                    continue
                try:
                    execute_query(pg, f'TRUNCATE TABLE "{name}" CASCADE')
                except Exception:
                    try:
                        execute_query(pg, f'DELETE FROM "{name}"')
                    except Exception:
                        pass
            pg.commit()

        for name, ddl in tables:
            if name in _SKIP_TABLES:
                continue
            sql = _ensure_if_not_exists(ddl, 'TABLE')
            execute_query(pg, sql)
        for name, ddl in indexes:
            sql = _ensure_if_not_exists(ddl, 'INDEX')
            try:
                execute_query(pg, sql)
            except Exception as exc:
                print(f'    index {name}: {exc}')
        pg.commit()

        copied = 0
        for name, _ddl in tables:
            if name in _SKIP_TABLES:
                continue
            n = _copy_table(sqlite_path, pg, name, chunk)
            print(f'  {name}: {n} rows')
            copied += n
        pg.commit()
        print(f'Done. Copied {copied} rows into {schema}. SQLite file is unchanged.')
        return 0
    finally:
        pg.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Copy one SQLite file into a Postgres schema')
    parser.add_argument('--schema', required=True, help='Postgres schema / domain key')
    parser.add_argument('--replace', action='store_true', help='Truncate target tables first')
    parser.add_argument('--chunk', type=int, default=5000, help='INSERT batch size')
    args = parser.parse_args()
    if not postgres_url():
        print('Set NCM_DATABASE_URL or NCM_APP_DATABASE_URL first.')
        return 2
    return migrate_schema(args.schema, replace=args.replace, chunk=max(100, args.chunk))


if __name__ == '__main__':
    raise SystemExit(main())
