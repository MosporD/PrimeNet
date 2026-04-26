"""
DB connections: SQLite (default) or PostgreSQL (schemas mirror former .db files).

PostgreSQL: set DB_ENGINE=postgresql and DATABASE_URL=postgresql://user:pass@host:5432/dbname
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_config import (
    HUAWEI_PM_DB,
    METADATA_DB,
    NOKIA_PM_DB,
    NCMUSERS_DB,
    SCHEMA_APP,
    SCHEMA_HUAWEI_PM,
    SCHEMA_METADATA,
    SCHEMA_NOKIA_PM,
    use_postgresql,
)

def is_postgresql() -> bool:
    return use_postgresql()


def adapt_placeholders(sql: str) -> str:
    if not use_postgresql():
        return sql
    return sql.replace('?', '%s')


def quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def execute_query(conn, sql: str, params=None):
    """Run SQL; returns a cursor-like object with ``fetchall`` / ``fetchone`` (SQLite or psycopg2)."""
    sql = adapt_placeholders(sql)
    params = params or ()
    if isinstance(conn, sqlite3.Connection):
        last_exc = None
        for _ in range(3):
            try:
                return conn.execute(sql, params)
            except sqlite3.OperationalError as exc:
                if 'database is locked' not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(0.15)
        raise last_exc
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    return cur


def _configure_sqlite_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    """
    Favor user-read resilience while background sync/watcher writes are active.
    WAL allows readers during writes; busy timeout/retries reduce lock errors.
    """
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA busy_timeout=120000')
    except Exception:
        pass
    return conn


def connect_app():
    if use_postgresql():
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO {SCHEMA_APP}')
        conn.commit()
        return conn
    conn = sqlite3.connect(NCMUSERS_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_metadata():
    if use_postgresql():
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO {SCHEMA_METADATA}')
        conn.commit()
        return conn
    conn = sqlite3.connect(METADATA_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_nokia_pm():
    if use_postgresql():
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO {SCHEMA_NOKIA_PM}')
        conn.commit()
        return conn
    conn = sqlite3.connect(NOKIA_PM_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_huawei_pm():
    if use_postgresql():
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO {SCHEMA_HUAWEI_PM}')
        conn.commit()
        return conn
    conn = sqlite3.connect(HUAWEI_PM_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def pm_union_alias(vendor: str) -> str:
    """Schema / attach alias for PM subqueries (single-vendor cell list)."""
    if use_postgresql():
        return SCHEMA_NOKIA_PM if vendor == 'Nokia' else SCHEMA_HUAWEI_PM
    return 'pm'


def performance_meta_pm_conn(vendor: str | None):
    """
    SQLite: metadata.db + ATTACH pm file(s).
    PostgreSQL: one connection, ``search_path`` lists metadata + relevant PM schema(s).
    Returns ``(connection, pm_alias)`` where ``pm_alias`` is truthy for single-vendor branch
    (SQLite: ``'pm'``, PostgreSQL: ``nokia_pm`` / ``huawei_pm`` schema name).
    """
    if not use_postgresql():
        conn = sqlite3.connect(METADATA_DB, timeout=120)
        conn = _configure_sqlite_conn(conn)
        if vendor == 'Nokia':
            conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS pm")
            return conn, 'pm'
        if vendor == 'Huawei':
            conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS pm")
            return conn, 'pm'
        conn.execute(f"ATTACH DATABASE '{NOKIA_PM_DB}'  AS nokia_pm")
        conn.execute(f"ATTACH DATABASE '{HUAWEI_PM_DB}' AS huawei_pm")
        return conn, None

    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)
    if vendor == 'Nokia':
        path = f'{SCHEMA_METADATA}, {SCHEMA_NOKIA_PM}'
        alias = SCHEMA_NOKIA_PM
    elif vendor == 'Huawei':
        path = f'{SCHEMA_METADATA}, {SCHEMA_HUAWEI_PM}'
        alias = SCHEMA_HUAWEI_PM
    else:
        path = f'{SCHEMA_METADATA}, {SCHEMA_NOKIA_PM}, {SCHEMA_HUAWEI_PM}'
        alias = None
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO {path}')
    conn.commit()
    return conn, alias


def postgres_table_columns(conn, schema: str, table: str) -> list[str]:
    cur = execute_query(
        conn,
        """
        SELECT column_name AS column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r['column_name'])
        else:
            out.append(r[0])
    return out
