"""
DB connections: SQLite only (local files under ``databases/``).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.activation_gate import install_sqlite_gate, require_activation

install_sqlite_gate()

from sync_config import (
    HUAWEI_PM_DB,
    METADATA_DB,
    NOKIA_PM_DB,
    NCMUSERS_DB,
)


def is_postgresql() -> bool:
    return False


def use_sqlite_for_app_and_metadata() -> bool:
    return True


def is_app_postgresql() -> bool:
    return False


def adapt_app_sql(sql: str) -> str:
    return sql


def adapt_placeholders(sql: str) -> str:
    return sql


def quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def execute_query(conn, sql: str, params=None):
    """Run SQL on a SQLite connection; returns a cursor with ``fetchall`` / ``fetchone``."""
    sql = adapt_placeholders(sql)
    params = params or ()
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError('Only sqlite3.Connection is supported')
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
    require_activation()
    conn = sqlite3.connect(NCMUSERS_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_metadata():
    require_activation()
    conn = sqlite3.connect(METADATA_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_nokia_pm():
    require_activation()
    conn = sqlite3.connect(NOKIA_PM_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def connect_huawei_pm():
    require_activation()
    conn = sqlite3.connect(HUAWEI_PM_DB, timeout=120)
    return _configure_sqlite_conn(conn)


def pm_union_alias(vendor: str) -> str:
    """Attach alias for PM subqueries (single-vendor cell list)."""
    return 'pm'


def performance_meta_pm_conn(vendor: str | None):
    """
    Open ``metadata.db`` and ATTACH the relevant PM file(s).
    Returns ``(connection, pm_alias)`` where ``pm_alias`` is ``'pm'`` for single-vendor
    or ``None`` when both vendors are attached.
    """
    require_activation()
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
