"""
DB connections.

Postgres-only runtime. Set ``NCM_DATABASE_URL`` (or ``NCM_APP_DATABASE_URL``
for app schema only). Domains are selected with ``NCM_PG_DOMAINS``; unset with
``NCM_DATABASE_URL`` enables every catalogued store.
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
    require_postgres_url,
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
    """Deprecated: always False under Postgres-only runtime."""
    return False


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


def _pg_params(params):
    if params is None:
        return ()
    return params if isinstance(params, (list, tuple, dict)) else tuple(params)


class PgConn:
    """Thin wrapper so existing ``conn.execute`` / ``cursor().execute`` callers keep working."""

    def __init__(self, raw, schema: str = 'public'):
        self._raw = raw
        self.schema = schema
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, _value):
        # Callers set sqlite3.Row; Postgres already uses PgRow via row_factory.
        self._row_factory = None

    def execute(self, sql, params=None):
        sql = adapt_sqlite_app_sql(sql)
        try:
            # Always pass params: psycopg only collapses the escaped ``%%`` back to ``%`` when it parses placeholders.
            return self._raw.execute(sql, _pg_params(params))
        except Exception as exc:
            _translate_pg_error(exc)

    def executemany(self, sql, seq_of_params):
        """Batch insert/update. psycopg3 Connection has no executemany — use a cursor."""
        sql = adapt_sqlite_app_sql(sql)
        try:
            cur = self._raw.cursor()
            try:
                return cur.executemany(sql, list(seq_of_params))
            finally:
                cur.close()
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
            return self._raw.execute(sql, _pg_params(params))
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

    def fetchmany(self, size=None):
        return self._raw.fetchmany(size) if size else self._raw.fetchmany()

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


def sqlite_ident(name: str) -> str:
    """Quote a SQL identifier (handles embedded double quotes).

    Table and column names cannot be parameterised, so anything interpolated
    into a statement goes through here. Previously copy-pasted into four
    modules; keep the single definition so a fix lands everywhere.
    """
    return '"' + str(name).replace('"', '""') + '"'


def sqlite_text_lit(value: object) -> str:
    """Quote a SQL text literal (single-quoted, escaped)."""
    return "'" + str(value).replace("'", "''") + "'"


def _pg_copy_value(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    try:
        import pandas as pd

        if isinstance(v, pd.Timestamp):
            return None if pd.isna(v) else v.to_pydatetime()
        if v is pd.NaT or v is pd.NA:
            return None
    except ImportError:
        pass
    if not isinstance(v, (str, bytes)) and hasattr(v, 'item'):
        v = v.item()
        if isinstance(v, float) and v != v:
            return None
    # int columns with blanks arrive as floats; "2" loads into BIGINT and DOUBLE alike.
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def df_to_sql(df, table: str, conn, *, if_exists: str = 'fail', index: bool = False, chunksize=None) -> None:
    """``DataFrame.to_sql`` that works on Postgres ``PgConn`` (pandas probes ``sqlite_master``).

    SQLite connections go straight to pandas. On Postgres rows are streamed with COPY;
    ``chunksize`` is accepted for call-site compatibility and ignored.
    """
    work = df if index is False else df.reset_index()
    if not _is_pg_conn(conn):
        work.to_sql(table, conn, if_exists=if_exists, index=False, chunksize=chunksize)
        return

    import pandas as pd

    cols = [str(c) for c in work.columns]
    seen: dict[bytes, str] = {}
    for c in cols:
        key = c.encode('utf-8')[:63].lower()
        if key in seen:
            raise ValueError(
                f'Columns {seen[key]!r} and {c!r} collide in table {table!r} after '
                'Postgres 63-byte identifier truncation'
            )
        seen[key] = c

    def _sql_type(series) -> str:
        # All-empty in this frame (often the first append chunk): keep TEXT so later chunks fit.
        if len(series) and series.isna().all():
            return 'TEXT'
        if pd.api.types.is_bool_dtype(series):
            return 'BOOLEAN'
        if pd.api.types.is_integer_dtype(series):
            return 'BIGINT'
        if pd.api.types.is_float_dtype(series):
            return 'DOUBLE PRECISION'
        if pd.api.types.is_datetime64_any_dtype(series):
            return 'TIMESTAMP'
        return 'TEXT'

    qtable = sqlite_ident(table)
    col_defs = ', '.join(f'{sqlite_ident(c)} {_sql_type(work[c])}' for c in cols)
    if if_exists == 'replace':
        execute_query(conn, f'DROP TABLE IF EXISTS {qtable} CASCADE')
        execute_query(conn, f'CREATE TABLE {qtable} ({col_defs})')
    elif if_exists == 'append':
        if not table_exists(conn, table):
            execute_query(conn, f'CREATE TABLE {qtable} ({col_defs})')
    elif if_exists == 'fail':
        if table_exists(conn, table):
            raise ValueError(f'Table {table} already exists')
        execute_query(conn, f'CREATE TABLE {qtable} ({col_defs})')
    else:
        raise ValueError(f'Unsupported if_exists={if_exists!r}')

    if work.empty or not cols:
        return

    raw = conn._raw if isinstance(conn, PgConn) else conn
    col_sql = ', '.join(sqlite_ident(c) for c in cols)
    try:
        with raw.cursor() as cur:
            with cur.copy(f'COPY {qtable} ({col_sql}) FROM STDIN') as copy:
                for row in work.itertuples(index=False, name=None):
                    copy.write_row([_pg_copy_value(v) for v in row])
    except Exception as exc:
        _translate_pg_error(exc)


def read_sql_query(sql: str, conn, *, params=None, chunksize=None):
    """``pandas.read_sql_query`` that works on Postgres ``PgConn``.

    pandas' DBAPI fallback turns rows into tuples by iterating them; ``PgRow`` is a
    dict, so that yields column names instead of values.
    """
    import pandas as pd

    if not _is_pg_conn(conn):
        return pd.read_sql_query(sql, conn, params=params, chunksize=chunksize)

    from psycopg.rows import tuple_row

    raw = conn._raw if isinstance(conn, PgConn) else conn
    cur = raw.cursor(row_factory=tuple_row)
    try:
        cur.execute(adapt_sqlite_app_sql(sql), _pg_params(params))
    except Exception as exc:
        cur.close()
        _translate_pg_error(exc)
    cols = [d.name for d in (cur.description or ())]
    if chunksize is None:
        try:
            return pd.DataFrame.from_records(cur.fetchall(), columns=cols)
        finally:
            cur.close()

    def _chunks():
        try:
            while True:
                rows = cur.fetchmany(int(chunksize))
                if not rows:
                    break
                yield pd.DataFrame.from_records(rows, columns=cols)
        finally:
            cur.close()

    return _chunks()


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


def _row_name(row, *, key: str = 'name', idx: int = 0) -> str:
    """Extract a table/column name from a SQLite Row or Postgres PgRow."""
    if isinstance(row, dict):
        val = row.get(key)
        if val is None and key == 'name':
            val = row.get('table_name')
        if val is None:
            val = next(iter(row.values()))
        return str(val)
    return str(row[idx])


def table_exists(conn, table: str) -> bool:
    """True when ``table`` exists (SQLite or Postgres)."""
    row = execute_query(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def list_tables(conn, *, like: str | None = None) -> list[str]:
    """User table names in the current schema/file (SQLite or Postgres)."""
    if like:
        rows = execute_query(
            conn,
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE ? AND name NOT LIKE 'sqlite_%'",
            (like,),
        ).fetchall()
    else:
        rows = execute_query(
            conn,
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        ).fetchall()
    return [_row_name(r) for r in rows]


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
    """True when the path maps to an enabled Postgres schema."""
    if not path:
        return False
    return schema_for_sqlite_path(path) is not None


def open_db(db_path: str, timeout: float = 120):
    """Open the Postgres schema mapped to this canonical store path."""
    require_activation()
    require_postgres_url()
    schema = schema_for_sqlite_path(db_path)
    if schema:
        return _connect_postgres(schema)
    raise RuntimeError(
        f'No Postgres schema mapped for store path {db_path!r}. '
        'Add it to db.pg_domains.canonical_sqlite_paths and DOMAIN_GROUPS, '
        'or enable the domain via NCM_PG_DOMAINS / NCM_DATABASE_URL.'
    )


def open_store(db_path: str, timeout: float = 60, *, wal: bool = True):
    """Open a module store on its Postgres schema (``wal`` ignored)."""
    return open_db(db_path, timeout=timeout)


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
    Open metadata and resolve the PM schema alias for ``alias."table"`` SQL.

    Postgres-only: one connection on schema ``metadata``; returned aliases are
    the PM schema names (Nokia/Huawei table names collide across vendors).
    """
    require_activation()
    require_postgres_url()
    if not is_domain_postgresql('metadata') or not is_domain_postgresql('pm'):
        raise RuntimeError(
            'Metadata and PM must both be enabled. Set NCM_DATABASE_URL '
            '(all domains) or NCM_PG_DOMAINS including metadata,pm.'
        )
    conn = _connect_postgres('metadata')
    nv = None if vendor is None or not str(vendor).strip() else str(vendor).strip()
    if nv is None:
        return conn, None
    schema = pm_schema(nv, scope)
    return conn, schema
