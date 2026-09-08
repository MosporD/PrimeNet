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


def qmark_to_percent(sql: str) -> str:
    """Replace ``?`` placeholders with ``%s``, ignoring quoted strings."""
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
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


def adapt_sqlite_app_sql(sql: str) -> str:
    """Rewrite SQLite DDL/DML so Postgres accepts it."""
    pragma = rewrite_pragma(sql)
    if pragma is not None:
        return qmark_to_percent(pragma)
    sql = rewrite_sqlite_master(sql)
    sql = rewrite_insert_or(sql)
    sql = _ON_CONFLICT_REPLACE.sub(r'UNIQUE (\1)', sql)
    sql = _ON_CONFLICT_REPLACE_BARE.sub('', sql)
    sql = _AUTOINC.sub('INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY', sql)
    sql = _BOOL_TRUE.sub('BOOLEAN DEFAULT TRUE', sql)
    sql = _BOOL_FALSE.sub('BOOLEAN DEFAULT FALSE', sql)
    sql = _ON_CONFLICT.sub('ON CONFLICT (', sql)
    sql = _EXCLUDED.sub('EXCLUDED.', sql)
    sql = _LAST_INSERT.sub('SELECT lastval()', sql)
    return qmark_to_percent(sql)
