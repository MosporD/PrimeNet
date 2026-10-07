"""DB connection for optimization cases (SQLite or Postgres domain ``cases``)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator

from core.cases import config


@contextmanager
def connect(*, dict_rows: bool = True) -> Iterator[Any]:
    from db.runtime import open_store

    conn = open_store(str(config.SQLITE_PATH), timeout=60)
    try:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        yield conn
    finally:
        conn.close()


_NAMED_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def _positional(sql: str, params: dict) -> tuple[str, tuple]:
    """Rewrite ``:name`` placeholders to ``?`` (the Postgres adapter only understands those)."""
    values: list[Any] = []

    def _sub(match: re.Match) -> str:
        values.append(params[match.group(1)])
        return "?"

    return _NAMED_PARAM.sub(_sub, sql), tuple(values)


def execute(conn, sql: str, params: tuple | list | dict | None = None):
    if isinstance(params, dict):
        sql, params = _positional(sql, params)
    cur = conn.cursor()
    cur.execute(sql, params or ())
    return cur


def fetchall(conn, sql: str, params: tuple | list | dict | None = None) -> list[dict]:
    cur = execute(conn, sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def fetchone(conn, sql: str, params: tuple | list | dict | None = None) -> dict | None:
    cur = execute(conn, sql, params)
    row = cur.fetchone()
    return dict(row) if row else None
