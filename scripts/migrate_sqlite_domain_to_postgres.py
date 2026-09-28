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
    if kind.upper() == 'INDEX':
        pattern = r'CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)'
        return re.sub(
            pattern,
            lambda m: f'CREATE {(m.group(1) or "")}INDEX IF NOT EXISTS ',
            ddl,
            count=1,
            flags=re.IGNORECASE,
        )
    pattern = rf'CREATE\s+{kind}\s+(?!IF\s+NOT\s+EXISTS)'
    return re.sub(pattern, f'CREATE {kind} IF NOT EXISTS ', ddl, count=1, flags=re.IGNORECASE)


def _soft_ddl(pg, sql: str, label: str) -> None:
    """Run optional DDL; roll back to a savepoint on failure so the txn stays usable."""
    try:
        execute_query(pg, 'SAVEPOINT ncm_migrate_ddl')
        execute_query(pg, sql)
        execute_query(pg, 'RELEASE SAVEPOINT ncm_migrate_ddl')
    except Exception as exc:
        try:
            execute_query(pg, 'ROLLBACK TO SAVEPOINT ncm_migrate_ddl')
        except Exception:
            try:
                pg.rollback()
            except Exception:
                pass
        print(f'    {label}: {exc}')


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


def _pg_typed_columns(pg, table: str, data_types: tuple[str, ...]) -> set[str]:
    try:
        rows = execute_query(
            pg,
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
            """,
            (table,),
        ).fetchall()
    except Exception:
        return set()
    want = {t.lower() for t in data_types}
    out: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            name = str(row.get('column_name') or '')
            dtype = str(row.get('data_type') or '').lower()
        else:
            name = str(row[0])
            dtype = str(row[1]).lower()
        if name and dtype in want:
            out.add(name)
    return out


def _username_id_map(pg) -> dict[str, int]:
    try:
        rows = execute_query(pg, 'SELECT id, username FROM users').fetchall()
    except Exception:
        return {}
    out: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            uid, name = row.get('id'), row.get('username')
        else:
            uid, name = row[0], row[1]
        if name is None or uid is None:
            continue
        out[str(name).strip().lower()] = int(uid)
    return out


def _coerce_value(col: str, value, *, bool_cols: set[str], int_cols: set[str], users: dict[str, int]):
    if value is None:
        return None
    if col in bool_cols and not isinstance(value, bool):
        if isinstance(value, (bytes, bytearray)):
            try:
                value = int(value)
            except Exception:
                return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        if isinstance(value, str) and value.strip() in ('0', '1'):
            return value.strip() == '1'
        return value
    if col in int_cols and not isinstance(value, int):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, float):
            return int(value)
        if isinstance(value, (bytes, bytearray)):
            try:
                return int(value)
            except Exception:
                return None
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit() or (text.startswith('-') and text[1:].isdigit()):
                return int(text)
            # Legacy activity_log rows stored username in user_id.
            if col.endswith('_id') or col == 'user_id':
                return users.get(text.lower())
            return None
    return value


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
        bool_cols = _pg_typed_columns(pg, table, ('boolean',)) & set(use_cols)
        int_cols = _pg_typed_columns(
            pg,
            table,
            ('integer', 'bigint', 'smallint'),
        ) & set(use_cols)
        users = _username_id_map(pg) if int_cols else {}
        col_sql = ', '.join(f'"{c}"' for c in use_cols)
        placeholders = ', '.join('?' for _ in use_cols)
        insert_sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'
        cur = src.execute(f'SELECT {col_sql} FROM "{table}"')
        copied = 0
        skipped = 0
        while True:
            batch = cur.fetchmany(chunk)
            if not batch:
                break
            rows = []
            for r in batch:
                vals = [
                    _coerce_value(
                        c,
                        r[c],
                        bool_cols=bool_cols,
                        int_cols=int_cols,
                        users=users,
                    )
                    for c in use_cols
                ]
                # Drop rows that still can't satisfy NOT NULL integer FKs like user_id.
                bad = False
                for c, v in zip(use_cols, vals):
                    if c in int_cols and v is None and r[c] is not None:
                        bad = True
                        break
                if bad:
                    skipped += 1
                    continue
                rows.append(tuple(vals))
            if not rows:
                continue
            try:
                pg.executemany(insert_sql, rows)
                copied += len(rows)
            except Exception:
                # Fall back to per-row so one bad legacy row does not kill the table.
                try:
                    pg.rollback()
                except Exception:
                    pass
                for row in rows:
                    try:
                        execute_query(pg, insert_sql, row)
                        copied += 1
                    except Exception:
                        skipped += 1
            if (copied + skipped) % (chunk * 5) == 0:
                pg.commit()
                print(f'    {table}: {copied} rows…')
        if skipped:
            print(f'    {table}: skipped {skipped} incompatible rows')
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
            _soft_ddl(pg, sql, f'table {name}')
        for name, ddl in indexes:
            sql = _ensure_if_not_exists(ddl, 'INDEX')
            _soft_ddl(pg, sql, f'index {name}')
        pg.commit()

        copied = 0
        for name, _ddl in tables:
            if name in _SKIP_TABLES:
                continue
            try:
                n = _copy_table(sqlite_path, pg, name, chunk)
                pg.commit()
                print(f'  {name}: {n} rows')
                copied += n
            except Exception as exc:
                try:
                    pg.rollback()
                except Exception:
                    pass
                print(f'  {name}: FAILED — {exc}')
                return 1
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
