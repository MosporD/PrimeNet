"""DB connection helpers for pm_plus (Postgres preferred, SQLite fallback)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from core.pm_plus import config


class PmPlusDbError(RuntimeError):
    pass


def _pg_connect():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise PmPlusDbError("psycopg2 is required when PM_PLUS_DATABASE_URL is set") from exc
    conn = psycopg2.connect(config.PM_PLUS_DATABASE_URL)
    conn.autocommit = False
    return conn, RealDictCursor


@contextmanager
def connect(*, dict_rows: bool = True) -> Iterator[Any]:
    """Yield a DB connection. Caller commits/rollbacks as needed for Postgres."""
    if config.use_postgres():
        conn, _cursor_factory = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{config.PM_PLUS_SCHEMA}", public')
            conn.commit()
            yield conn
        finally:
            conn.close()
        return

    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.SQLITE_PATH), timeout=60)
    conn.row_factory = sqlite3.Row if dict_rows else None
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
    finally:
        conn.close()


def execute(conn, sql: str, params: tuple | list | dict | None = None):
    """Run SQL with engine-neutral placeholders (:name or ?)."""
    params = params or ()
    if config.use_postgres():
        cur = conn.cursor()
        # Convert ? to %s for psycopg2 when using positional params
        if isinstance(params, (list, tuple)) and "?" in sql:
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        return cur
    cur = conn.cursor()
    if isinstance(params, dict) and config.use_postgres() is False:
        # sqlite3 supports :name
        cur.execute(sql, params)
    elif isinstance(params, dict):
        cur.execute(sql, params)
    else:
        cur.execute(sql, params)
    return cur


def fetchall(conn, sql: str, params: tuple | list | dict | None = None) -> list[dict]:
    cur = execute(conn, sql, params)
    rows = cur.fetchall()
    if not rows:
        return []
    if config.use_postgres():
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def fetchone(conn, sql: str, params: tuple | list | dict | None = None) -> dict | None:
    rows = fetchall(conn, sql, params)
    return rows[0] if rows else None


def qident(name: str) -> str:
    """Schema-qualify a table for Postgres; plain name for SQLite."""
    if config.use_postgres():
        return f'"{config.PM_PLUS_SCHEMA}"."{name}"'
    return name
