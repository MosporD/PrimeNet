"""Translate SQLite-shaped SQL to PostgreSQL.

Used by every Postgres domain (app, metadata, PM, neighbors, groups, balance).
SQLite connections must not call this.
"""

from __future__ import annotations

import re

_AUTOINC = re.compile(
    r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT',
    re.IGNORECASE,
)
_BOOL_TRUE = re.compile(r'BOOLEAN\s+DEFAULT\s+1\b', re.IGNORECASE)
_BOOL_FALSE = re.compile(r'BOOLEAN\s+DEFAULT\s+0\b', re.IGNORECASE)
_ON_CONFLICT = re.compile(r'ON\s+CONFLICT\s*\(', re.IGNORECASE)
_LAST_INSERT = re.compile(r'SELECT\s+last_insert_rowid\s*\(\s*\)', re.IGNORECASE)
_ON_CONFLICT_REPLACE = re.compile(
    r'UNIQUE\s*\(\s*([^)]+)\)\s*ON\s+CONFLICT\s+REPLACE',
    re.IGNORECASE,
)
_ON_CONFLICT_REPLACE_BARE = re.compile(r'\s+ON\s+CONFLICT\s+REPLACE\b', re.IGNORECASE)
_EXCLUDED = re.compile(r'\bexcluded\.', re.IGNORECASE)
_PRAGMA_TABLE_INFO = re.compile(
    r'^\s*PRAGMA\s+table_info\s*\(\s*(?:"([^"]+)"|([A-Za-z_][\w$]*))\s*\)\s*;?\s*$',
    re.IGNORECASE,
)
_PRAGMA_ANY = re.compile(r'^\s*PRAGMA\b', re.IGNORECASE)
_INSERT_OR_IGNORE = re.compile(r'^\s*INSERT\s+OR\s+IGNORE\s+INTO\b', re.IGNORECASE)
_INSERT_OR_REPLACE = re.compile(r'^\s*INSERT\s+OR\s+REPLACE\s+INTO\b', re.IGNORECASE)
_INSERT_COLS = re.compile(
    r'INSERT\s+INTO\s+(?:"[^"]+"|[\w.]+)\s*\(([^)]+)\)',
    re.IGNORECASE,
)
_SQLITE_MASTER = re.compile(r'\bsqlite_master\b', re.IGNORECASE)
_SELECT_SQL_MASTER = re.compile(
    r"SELECT\s+sql\s+FROM\s+sqlite_master\b",
    re.IGNORECASE,
)
_COLLATE_NOCASE = re.compile(r'\s+COLLATE\s+NOCASE\b', re.IGNORECASE)
# SQLite callers sometimes write empty string as "" (empty identifier on PG).
_EMPTY_DQUOTE_COMPARE = re.compile(
    r'(<>|!=|=)\s*""',
)
_EMPTY_DQUOTE_COMPARE_LEFT = re.compile(
    r'""\s*(<>|!=|=)',
)


_CAST_OPEN = re.compile(r'\bCAST\s*\(', re.IGNORECASE)
_CAST_AS_TYPE = re.compile(r'^(.*)\s+AS\s+([A-Za-z]+(?:\s+PRECISION)?)\s*$', re.IGNORECASE | re.DOTALL)
_REAL_TYPES = {'real', 'float', 'double', 'double precision', 'numeric'}
_INT_TYPES = {'integer', 'int', 'bigint'}

# SQLite CAST semantics: leading numeric prefix, else 0; NULL stays NULL.
PG_SAFE_CAST_FUNCTIONS_SQL = (
    "CREATE OR REPLACE FUNCTION public.ncm_real(v text) RETURNS double precision "
    "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$ SELECT CASE WHEN v IS NULL THEN NULL ELSE COALESCE("
    "substring(v from '^\\s*([-+]?(?:[0-9]+\\.?[0-9]*|\\.[0-9]+)(?:[eE][-+]?[0-9]+)?)')::double precision, 0) END $f$",
    "CREATE OR REPLACE FUNCTION public.ncm_int(v text) RETURNS bigint "
    "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$ SELECT CASE WHEN v IS NULL THEN NULL ELSE COALESCE("
    "trunc(substring(v from '^\\s*([-+]?(?:[0-9]+\\.?[0-9]*|\\.[0-9]+)(?:[eE][-+]?[0-9]+)?)')::double precision)::bigint, 0) END $f$",
)


def _matching_paren(sql: str, open_idx: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_idx*, skipping quoted text; -1 if none."""
    depth = 0
    quote = ''
    i = open_idx
    n = len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    i += 2
                    continue
                quote = ''
        elif ch in ("'", '"'):
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def rewrite_numeric_casts(sql: str) -> str:
    """``CAST(x AS REAL|INTEGER)`` → ``public.ncm_real/ncm_int(x::text)`` (SQLite-lenient)."""
    if not _CAST_OPEN.search(sql):
        return sql
    out: list[str] = []
    quote = ''
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ''
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        m = _CAST_OPEN.match(sql, i) if ch in 'cC' else None
        if m and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == '_')):
            open_idx = m.end() - 1
            close_idx = _matching_paren(sql, open_idx)
            if close_idx > 0:
                inner = rewrite_numeric_casts(sql[open_idx + 1:close_idx])
                typed = _CAST_AS_TYPE.match(inner)
                kind = ' '.join(typed.group(2).lower().split()) if typed else ''
                if kind in _REAL_TYPES:
                    out.append(f'public.ncm_real(({typed.group(1).strip()})::text)')
                elif kind in _INT_TYPES:
                    out.append(f'public.ncm_int(({typed.group(1).strip()})::text)')
                else:
                    out.append(sql[i:open_idx + 1] + inner + ')')
                i = close_idx + 1
                continue
        out.append(ch)
        i += 1
    return ''.join(out)


def qmark_to_percent(sql: str) -> str:
    """Replace ``?`` placeholders with ``%s``, escaping literal ``%`` for psycopg.

    Must be idempotent: callers such as ``database_enhanced._exec`` adapt SQL
    and ``PgConn.execute`` adapts it again. Existing ``%%`` escapes are kept,
    and ``%s`` outside single-quoted literals is kept as a placeholder.
    """
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ''
        if ch == '%':
            if nxt == '%':
                out.append('%%')
                i += 2
                continue
            if nxt == 's' and not in_single:
                out.append('%s')
                i += 2
                continue
            out.append('%%')
        elif ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == '?' and not in_single and not in_double:
            out.append('%s')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def rewrite_pragma(sql: str) -> str | None:
    """Return Postgres SQL for a SQLite PRAGMA, or None if *sql* is not a PRAGMA."""
    stripped = sql.strip()
    match = _PRAGMA_TABLE_INFO.match(stripped)
    if match:
        table = match.group(1) or match.group(2)
        return (
            'SELECT (ordinal_position - 1) AS cid, column_name AS name, '
            'data_type AS type, '
            "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, "
            'column_default AS dflt_value, 0 AS pk '
            'FROM information_schema.columns '
            f'WHERE table_schema = current_schema() AND table_name = {_sql_string_literal(table)} '
            'ORDER BY ordinal_position'
        )
    if _PRAGMA_ANY.match(stripped):
        return 'SELECT 1 WHERE false'
    return None


def rewrite_sqlite_master(sql: str) -> str:
    if not _SQLITE_MASTER.search(sql):
        return sql
    if _SELECT_SQL_MASTER.search(sql):
        return 'SELECT NULL AS sql WHERE false'
    # Existence probe used across loaders / map / health checks.
    sql = re.sub(
        r"SELECT\s+1\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'\s+"
        r"AND\s+name\s*=\s*\?",
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
        "AND table_name = ?",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"SELECT\s+name\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'",
        "SELECT table_name AS name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"AND\s+name\s+NOT\s+LIKE\s+'sqlite_%'", '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bAND\s+name\b', 'AND table_name', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bORDER BY name\b', 'ORDER BY table_name', sql, flags=re.IGNORECASE)
    return sql


def _insert_column_names(sql: str) -> list[str]:
    match = _INSERT_COLS.search(sql)
    if not match:
        return []
    names = []
    for raw in match.group(1).split(','):
        name = raw.strip().strip('"')
        if name:
            names.append(name)
    return names


def rewrite_insert_or(sql: str) -> str:
    kind = None
    if _INSERT_OR_IGNORE.match(sql):
        kind = 'ignore'
        sql = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', sql, count=1, flags=re.IGNORECASE)
    elif _INSERT_OR_REPLACE.match(sql):
        kind = 'replace'
        sql = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', sql, count=1, flags=re.IGNORECASE)
    if kind is None or re.search(r'\bON\s+CONFLICT\b', sql, re.IGNORECASE):
        return sql
    body = sql.rstrip().rstrip(';')
    if kind == 'ignore':
        return body + ' ON CONFLICT DO NOTHING'
    cols = _insert_column_names(sql)
    lower = {c.lower() for c in cols}
    if 'cell_name' in lower and 'timestamp' in lower:
        updates = [
            f'"{c}" = EXCLUDED."{c}"'
            for c in cols
            if c.lower() not in ('cell_name', 'timestamp')
        ]
        if updates:
            return (
                body
                + ' ON CONFLICT (cell_name, timestamp) DO UPDATE SET '
                + ', '.join(updates)
            )
        return body + ' ON CONFLICT (cell_name, timestamp) DO NOTHING'
    return body + ' ON CONFLICT DO NOTHING'


def rewrite_empty_double_quoted_literals(sql: str) -> str:
    """Map ``= ""`` / ``<> ""`` style empty strings to proper ``''`` literals."""
    sql = _EMPTY_DQUOTE_COMPARE.sub(r"\1 ''", sql)
    sql = _EMPTY_DQUOTE_COMPARE_LEFT.sub(r"'' \1", sql)
    return sql


def adapt_sqlite_app_sql(sql: str) -> str:
    """Rewrite SQLite DDL/DML so Postgres accepts it."""
    pragma = rewrite_pragma(sql)
    if pragma is not None:
        return qmark_to_percent(pragma)
    sql = rewrite_sqlite_master(sql)
    sql = rewrite_numeric_casts(sql)
    sql = rewrite_empty_double_quoted_literals(sql)
    sql = rewrite_insert_or(sql)
    sql = _ON_CONFLICT_REPLACE.sub(r'UNIQUE (\1)', sql)
    sql = _ON_CONFLICT_REPLACE_BARE.sub('', sql)
    sql = _AUTOINC.sub('INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY', sql)
    sql = _BOOL_TRUE.sub('BOOLEAN DEFAULT TRUE', sql)
    sql = _BOOL_FALSE.sub('BOOLEAN DEFAULT FALSE', sql)
    sql = _ON_CONFLICT.sub('ON CONFLICT (', sql)
    sql = _EXCLUDED.sub('EXCLUDED.', sql)
    sql = _LAST_INSERT.sub('SELECT lastval()', sql)
    sql = _COLLATE_NOCASE.sub('', sql)
    return qmark_to_percent(sql)
