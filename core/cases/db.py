"""DB connection for optimization cases (SQLite under databases/cases/)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from core.cases import config


@contextmanager
def connect(*, dict_rows: bool = True) -> Iterator[sqlite3.Connection]:
    config.CASES_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.SQLITE_PATH), timeout=60)
    if dict_rows:
        conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def execute(conn: sqlite3.Connection, sql: str, params: tuple | list | dict | None = None):
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple | list | dict | None = None) -> list[dict]:
    cur = execute(conn, sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def fetchone(conn: sqlite3.Connection, sql: str, params: tuple | list | dict | None = None) -> dict | None:
    cur = execute(conn, sql, params)
    row = cur.fetchone()
    return dict(row) if row else None
