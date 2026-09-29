"""DB connection helpers for pm_plus (Postgres via open_store)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from core.pm_plus import config


class PmPlusDbError(RuntimeError):
    pass


@contextmanager
def connect(*, dict_rows: bool = True) -> Iterator[Any]:
    """Yield a DB connection. Caller commits/rollbacks as needed."""
    from db.runtime import open_store, schema_for_sqlite_path
    from sync_config import PM_PLUS_DB

    cfg_path = str(config.SQLITE_PATH)
    path = cfg_path if schema_for_sqlite_path(cfg_path) else PM_PLUS_DB
    conn = open_store(path, timeout=60)
    try:
        yield conn
    finally:
        conn.close()


def execute(conn, sql: str, params: tuple | list | dict | None = None):
    """Run SQL with engine-neutral placeholders (:name or ?)."""
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur


def fetchall(conn, sql: str, params: tuple | list | dict | None = None) -> list[dict]:
    cur = execute(conn, sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def fetchone(conn, sql: str, params: tuple | list | dict | None = None) -> dict | None:
    rows = fetchall(conn, sql, params)
    return rows[0] if rows else None


def qident(name: str) -> str:
    """Schema-qualify a table for the pm_plus Postgres schema."""
    return f'"{config.PM_PLUS_SCHEMA}"."{name}"'
