"""
DB connections.

SQLite by default. Opt in per domain with ``NCM_DATABASE_URL`` /
``NCM_APP_DATABASE_URL`` and ``NCM_PG_DOMAINS``. Unmapped files (femto, SON
ML, KPI headers, …) always stay SQLite.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.activation_gate import install_sqlite_gate, require_activation
from db.app_sql import adapt_sqlite_app_sql
from db.pg_domains import (
    enabled_groups,
    is_domain_postgresql,
    pm_schema,
    postgres_url,
    schema_for_sqlite_path,
)

install_sqlite_gate()

from sync_config import (
    HUAWEI_PM_DAILY_DB,
    HUAWEI_PM_DB,
    METADATA_DB,
    NETWORK_BALANCE_DB,
    NOKIA_PM_DAILY_DB,
    NOKIA_PM_DB,
    NCMUSERS_DB,
    SQLITE_PM_CACHE_SIZE_KB,
    SQLITE_PM_MMAP_SIZE_MB,
)


def app_database_url() -> str:
    return postgres_url()


def is_postgresql() -> bool:
    """True when any Postgres domain is enabled."""
    return bool(enabled_groups())


def use_sqlite_for_app_and_metadata() -> bool:
    return not is_domain_postgresql('app') and not is_domain_postgresql('metadata')


def is_app_postgresql() -> bool:
    return is_domain_postgresql('app')


def adapt_app_sql(sql: str) -> str:
    if not is_app_postgresql():
        return sql
    return adapt_sqlite_app_sql(sql)


def adapt_placeholders(sql: str) -> str:
    """Legacy helper. Postgres conversion happens inside ``PgConn.execute``."""
    return sql


def quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


class PgRow(dict):
    """dict that also accepts integer indexes like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(dict.values(self))[key]
        return dict.__getitem__(self, key)


def _pg_row_factory(cursor):
    fields = [d.name for d in (cursor.description or ())]

    def make_row(values):
        return PgRow(zip(fields, values))

    return make_row


def _translate_pg_error(exc):
    try:
        from psycopg.errors import Error as PgError
        from psycopg.errors import IntegrityError as PgIntegrity
        from psycopg.errors import UndefinedColumn
        from psycopg.errors import UndefinedObject
        from psycopg.errors import UndefinedTable
        from psycopg.errors import UniqueViolation
    except ImportError:
        raise exc
    if isinstance(exc, UniqueViolation):
        raise sqlite3.IntegrityError(str(exc)) from exc
    if isinstance(exc, PgIntegrity):
        raise sqlite3.IntegrityError(str(exc)) from exc
    if isinstance(exc, (UndefinedTable, UndefinedColumn, UndefinedObject, PgError)):
        raise sqlite3.OperationalError(str(exc)) from exc
    raise exc


class PgConn:
    """Thin wrapper so existing ``conn.execute`` / ``cursor().execute`` callers keep working."""

    def __init__(self, raw, schema: str = 'public'):
        self._raw = raw
        self.schema = schema

    def execute(self, sql, params=None):
        sql = adapt_sqlite_app_sql(sql)
        try:
            if params is None:
                return self._raw.execute(sql)
            return self._raw.execute(sql, tuple(params) if not isinstance(params, (list, tuple)) else params)
        except Exception as exc:
            _translate_pg_error(exc)

    def executemany(self, sql, seq_of_params):
        sql = adapt_sqlite_app_sql(sql)
        try:
            return self._raw.executemany(sql, seq_of_params)
        except Exception as exc:
            _translate_pg_error(exc)

    def executescript(self, sql: str):
        for part in sql.split(';'):
            stmt = part.strip()
            if stmt:
                self.execute(stmt)

    def cursor(self):
        return PgCursor(self._raw.cursor())

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._raw.__exit__(*exc)


class PgCursor:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        sql = adapt_sqlite_app_sql(sql)
        try:
            if params is None:
                return self._raw.execute(sql)
            return self._raw.execute(sql, tuple(params) if not isinstance(params, (list, tuple)) else params)
        except Exception as exc:
            _translate_pg_error(exc)

    def executemany(self, sql, seq_of_params):
        sql = adapt_sqlite_app_sql(sql)
        try:
            return self._raw.executemany(sql, seq_of_params)
        except Exception as exc:
            _translate_pg_error(exc)

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()

    @property
    def lastrowid(self):
        return getattr(self._raw, 'lastrowid', None)

    @property
    def rowcount(self):
        return self._raw.rowcount

    @property
    def description(self):
        return self._raw.description

    def close(self):
        return self._raw.close()

    def __iter__(self):
        return iter(self._raw)


AppPgConn = PgConn
AppPgCursor = PgCursor


def _is_pg_conn(conn) -> bool:
    if isinstance(conn, PgConn):
        return True
    mod = type(conn).__module__ or ''
    return mod.startswith('psycopg')


def execute_query(conn, sql: str, params=None):
    """Run SQL. SQLite uses ``?``; Postgres connections are adapted automatically."""
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
    if _is_pg_conn(conn):
        return conn.execute(sql, params)
    raise TypeError(f'Unsupported connection type: {type(conn)!r}')


def table_columns(conn, table: str) -> set[str]:
    """Column names for ``table`` on SQLite or Postgres."""
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(f'PRAGMA table_info("{table}")')
        return {str(row[1]) for row in cur.fetchall()}
    cur = execute_query(conn, f'PRAGMA table_info("{table}")')
    names: set[str] = set()
    for row in cur.fetchall():
        if isinstance(row, dict):
            names.add(str(row.get('name') or row.get('column_name') or next(iter(row.values()))))
        else:
            names.add(str(row[1] if len(row) > 1 else row[0]))
    return names


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


def apply_pm_read_pragmas(conn) -> None:
    """Tune SQLite for large PM reads. No-op on Postgres."""
    if not isinstance(conn, sqlite3.Connection):
        return
    from core.load_monitor import effective_sqlite_cache_kb, effective_sqlite_mmap_mb

    cache_kb = effective_sqlite_cache_kb(SQLITE_PM_CACHE_SIZE_KB)
    mmap_mb = effective_sqlite_mmap_mb(SQLITE_PM_MMAP_SIZE_MB)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA temp_store=MEMORY')
    except Exception:
        pass
    if cache_kb > 0:
        try:
            conn.execute(f'PRAGMA cache_size=-{int(cache_kb)}')
        except Exception:
            pass
    if mmap_mb > 0:
        try:
            conn.execute(f'PRAGMA mmap_size={int(mmap_mb) * 1024 * 1024}')
        except Exception:
            pass


def _connect_postgres(schema: str) -> PgConn:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            'A PostgreSQL URL is set but psycopg is not installed. '
            'pip install "psycopg[binary]"'
        ) from exc
    ident = quote_ident(schema)
    raw = psycopg.connect(
        postgres_url(),
        row_factory=_pg_row_factory,
        connect_timeout=10,
    )
    raw.execute(f'CREATE SCHEMA IF NOT EXISTS {ident}')
    raw.execute(f'SET search_path TO {ident}, public')
    raw.commit()
    return PgConn(raw, schema=schema)


def store_available(path: str | None) -> bool:
    """True when the canonical SQLite file exists, or its Postgres schema is enabled."""
    if not path:
        return False
    if schema_for_sqlite_path(path):
        return True
    return os.path.isfile(path)


def open_db(db_path: str, timeout: float = 120):
    """Open a canonical SQLite file, or the mapped Postgres schema when enabled."""
    require_activation()
    schema = schema_for_sqlite_path(db_path)
    if schema:
        return _connect_postgres(schema)
    conn = sqlite3.connect(db_path, timeout=timeout)
    return _configure_sqlite_conn(conn)


def connect_app():
    require_activation()
    return open_db(NCMUSERS_DB)


def connect_metadata():
    require_activation()
    return open_db(METADATA_DB)


def connect_nokia_pm():
    require_activation()
    return open_db(NOKIA_PM_DB)


def connect_huawei_pm():
    require_activation()
    return open_db(HUAWEI_PM_DB)


def connect_network_balance():
    require_activation()
    return open_db(NETWORK_BALANCE_DB)


def connect_pm_db(db_path: str):
    """Open any PM/group/neighbor SQLite file, or its Postgres schema when mapped."""
    return open_db(db_path)


def pm_union_alias(vendor: str) -> str:
    """Attach alias for PM subqueries (single-vendor cell list)."""
    if is_domain_postgresql('pm'):
        return pm_schema(vendor, 'hourly')
    return 'pm'


def _pm_sqlite_path(vendor: str, scope: str = 'hourly') -> str:
    daily = str(scope or 'hourly').strip().lower() in ('d', 'day', 'daily')
    huawei = str(vendor or '').strip().lower().startswith('huawei')
    if huawei:
        return HUAWEI_PM_DAILY_DB if daily else HUAWEI_PM_DB
    return NOKIA_PM_DAILY_DB if daily else NOKIA_PM_DB


def performance_meta_pm_conn(vendor: str | None, scope: str = 'hourly'):
    """
    Open metadata and the relevant PM store(s).

    SQLite: ATTACH PM files as ``pm`` / ``nokia_pm`` / ``huawei_pm``.
    Postgres: one connection on schema ``metadata``; returned aliases are the
    PM schema names so ``alias."table"`` stays valid (Nokia/Huawei table names collide).
    """
    require_activation()
    meta_pg = is_domain_postgresql('metadata')
    pm_pg = is_domain_postgresql('pm')
    if meta_pg != pm_pg:
        raise RuntimeError(
            'Metadata and PM must use the same backend. Enable both in NCM_PG_DOMAINS '
            '(metadata,pm) or leave both on SQLite.'
        )
    if meta_pg:
        conn = _connect_postgres('metadata')
        nv = None if vendor is None or not str(vendor).strip() else str(vendor).strip()
        if nv is None:
            return conn, None
        schema = pm_schema(nv, scope)
        return conn, schema

    conn = sqlite3.connect(METADATA_DB, timeout=120)
    conn = _configure_sqlite_conn(conn)
    if vendor == 'Nokia' or (isinstance(vendor, str) and vendor.strip().lower() == 'nokia'):
        conn.execute(f"ATTACH DATABASE '{_pm_sqlite_path('Nokia', scope)}'  AS pm")
        return conn, 'pm'
    if vendor == 'Huawei' or (isinstance(vendor, str) and vendor.strip().lower().startswith('huawei')):
        conn.execute(f"ATTACH DATABASE '{_pm_sqlite_path('Huawei', scope)}' AS pm")
        return conn, 'pm'
    if vendor is None or (isinstance(vendor, str) and not str(vendor).strip()):
        conn.execute(f"ATTACH DATABASE '{_pm_sqlite_path('Nokia', scope)}'  AS nokia_pm")
        conn.execute(f"ATTACH DATABASE '{_pm_sqlite_path('Huawei', scope)}' AS huawei_pm")
        return conn, None
    conn.execute(f"ATTACH DATABASE '{_pm_sqlite_path('Nokia', scope)}'  AS pm")
    return conn, 'pm'
