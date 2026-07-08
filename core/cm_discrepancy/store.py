"""SQLite persistence for CM discrepancy audit runs.

Database: ``{DATABASES_ROOT}/radio/cm_discrepancy.db``. Detail rows are stored
for flagged objects only (mismatched / added / removed); Master and Summary
cover every parameter observed in the run.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from sync_config import DATABASES_ROOT

DB_PATH = os.path.join(DATABASES_ROOT, 'radio', 'cm_discrepancy.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT NOT NULL,
    run_date TEXT NOT NULL,          -- ISO YYYY-MM-DD
    scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',  -- running|success|partial|failed
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_run_vendor_date ON audit_run(vendor, run_date);

CREATE TABLE IF NOT EXISTS audit_master (
    run_id INTEGER NOT NULL,
    mo TEXT NOT NULL,
    parameter TEXT NOT NULL,
    distribution TEXT NOT NULL DEFAULT '',
    common_setting TEXT NOT NULL DEFAULT '',
    unique_count INTEGER NOT NULL DEFAULT 0,
    total_samples INTEGER NOT NULL DEFAULT 0,
    mismatch_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_master_run ON audit_master(run_id, mo);

CREATE TABLE IF NOT EXISTS audit_summary (
    run_id INTEGER NOT NULL,
    mo TEXT NOT NULL,
    parameter TEXT NOT NULL,
    mismatch_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_summary_run ON audit_summary(run_id, mo);

CREATE TABLE IF NOT EXISTS audit_detail (
    run_id INTEGER NOT NULL,
    mo TEXT NOT NULL,
    object_key TEXT NOT NULL,
    ne_name TEXT NOT NULL DEFAULT '',
    flag TEXT NOT NULL,              -- mismatched|added|removed
    mismatch_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}',
    detected_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_detail_run ON audit_detail(run_id, mo, flag);

CREATE TABLE IF NOT EXISTS audit_trend (
    vendor TEXT NOT NULL,
    run_date TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    total_mismatches INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (vendor, run_date)
);

CREATE TABLE IF NOT EXISTS audit_object_index (
    run_id INTEGER NOT NULL,
    mo TEXT NOT NULL,
    object_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_object_index_run ON audit_object_index(run_id, mo);
"""


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def create_run(conn: sqlite3.Connection, *, vendor: str, run_date: str, scope: str = '') -> int:
    cur = conn.execute(
        'INSERT INTO audit_run (vendor, run_date, scope, status, started_at) '
        "VALUES (?, ?, ?, 'running', ?)",
        (vendor, run_date, scope, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    stats: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        'UPDATE audit_run SET status = ?, finished_at = ?, stats_json = ? WHERE id = ?',
        (status, _now(), json.dumps(stats or {}, default=str), run_id),
    )
    conn.commit()


def delete_run_payload(conn: sqlite3.Connection, run_id: int) -> None:
    """Remove data rows for a run (used before re-running the same day)."""
    for table in ('audit_master', 'audit_summary', 'audit_detail', 'audit_object_index'):
        conn.execute(f'DELETE FROM {table} WHERE run_id = ?', (run_id,))
    conn.commit()


def supersede_runs(conn: sqlite3.Connection, *, vendor: str, run_date: str) -> None:
    """Drop older runs for the same vendor+date so a re-run replaces them."""
    rows = conn.execute(
        'SELECT id FROM audit_run WHERE vendor = ? AND run_date = ?',
        (vendor, run_date),
    ).fetchall()
    for row in rows:
        delete_run_payload(conn, int(row['id']))
        conn.execute('DELETE FROM audit_run WHERE id = ?', (int(row['id']),))
    conn.execute('DELETE FROM audit_trend WHERE vendor = ? AND run_date = ?', (vendor, run_date))
    conn.commit()


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_master(conn: sqlite3.Connection, run_id: int, mo: str, rows: list[dict[str, Any]]) -> None:
    conn.executemany(
        'INSERT INTO audit_master (run_id, mo, parameter, distribution, common_setting, '
        'unique_count, total_samples, mismatch_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (
                run_id, mo, row['parameter'], row['distribution'], row['common_setting'],
                int(row['unique_count']), int(row['total_samples']), int(row['mismatch_count']),
            )
            for row in rows
        ],
    )
    conn.commit()


def write_summary(conn: sqlite3.Connection, run_id: int, mo: str, rows: list[dict[str, Any]]) -> None:
    conn.executemany(
        'INSERT INTO audit_summary (run_id, mo, parameter, mismatch_count) VALUES (?, ?, ?, ?)',
        [(run_id, mo, row['parameter'], int(row['mismatch_count'])) for row in rows],
    )
    conn.commit()


def write_detail(conn: sqlite3.Connection, run_id: int, mo: str, rows: list[dict[str, Any]]) -> None:
    detected = datetime.now().strftime('%Y-%m-%d')
    conn.executemany(
        'INSERT INTO audit_detail (run_id, mo, object_key, ne_name, flag, mismatch_json, '
        'payload_json, detected_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (
                run_id, mo, row['object_key'], row.get('ne_name') or '', row['flag'],
                json.dumps(row.get('mismatches') or [], default=str),
                json.dumps(row.get('payload') or {}, default=str),
                row.get('detected_date') or detected,
            )
            for row in rows
        ],
    )
    conn.commit()


def write_object_index(conn: sqlite3.Connection, run_id: int, mo: str, object_keys: list[str]) -> None:
    conn.executemany(
        'INSERT INTO audit_object_index (run_id, mo, object_key) VALUES (?, ?, ?)',
        [(run_id, mo, key) for key in object_keys],
    )
    conn.commit()


def append_trend(conn: sqlite3.Connection, *, vendor: str, run_date: str, run_id: int, total: int) -> None:
    conn.execute(
        'INSERT INTO audit_trend (vendor, run_date, run_id, total_mismatches) VALUES (?, ?, ?, ?) '
        'ON CONFLICT(vendor, run_date) DO UPDATE SET run_id = excluded.run_id, '
        'total_mismatches = excluded.total_mismatches',
        (vendor, run_date, run_id, int(total)),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def list_runs(conn: sqlite3.Connection, *, vendor: str = '', limit: int = 60) -> list[dict[str, Any]]:
    where = 'WHERE vendor = ?' if vendor else ''
    params: list[Any] = [vendor] if vendor else []
    params.append(int(limit))
    rows = conn.execute(
        f'SELECT * FROM audit_run {where} ORDER BY run_date DESC, id DESC LIMIT ?',
        params,
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item['stats'] = json.loads(item.pop('stats_json') or '{}')
        except ValueError:
            item['stats'] = {}
        out.append(item)
    return out


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute('SELECT * FROM audit_run WHERE id = ?', (run_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item['stats'] = json.loads(item.pop('stats_json') or '{}')
    except ValueError:
        item['stats'] = {}
    return item


def find_run(conn: sqlite3.Connection, *, vendor: str, run_date: str) -> dict[str, Any] | None:
    row = conn.execute(
        'SELECT id FROM audit_run WHERE vendor = ? AND run_date = ? ORDER BY id DESC LIMIT 1',
        (vendor, run_date),
    ).fetchone()
    return get_run(conn, int(row['id'])) if row else None


def previous_successful_run(
    conn: sqlite3.Connection,
    *,
    vendor: str,
    before_run_id: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id FROM audit_run WHERE vendor = ? AND id < ? AND status IN ('success', 'partial') "
        'ORDER BY id DESC LIMIT 1',
        (vendor, before_run_id),
    ).fetchone()
    return get_run(conn, int(row['id'])) if row else None


def get_object_keys(conn: sqlite3.Connection, run_id: int, mo: str) -> set[str]:
    rows = conn.execute(
        'SELECT object_key FROM audit_object_index WHERE run_id = ? AND mo = ?',
        (run_id, mo),
    ).fetchall()
    return {str(row['object_key']) for row in rows}


def get_summary(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT mo, parameter, mismatch_count FROM audit_summary WHERE run_id = ? '
        'ORDER BY mismatch_count DESC, mo, parameter',
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_master(conn: sqlite3.Connection, run_id: int, *, mo: str = '') -> list[dict[str, Any]]:
    where = 'run_id = ?'
    params: list[Any] = [run_id]
    if mo:
        where += ' AND mo = ?'
        params.append(mo)
    rows = conn.execute(
        f'SELECT mo, parameter, distribution, common_setting, unique_count, total_samples, '
        f'mismatch_count FROM audit_master WHERE {where} ORDER BY mo, parameter',
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_detail_mos(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT mo, flag, COUNT(*) AS n FROM audit_detail WHERE run_id = ? GROUP BY mo, flag',
        (run_id,),
    ).fetchall()
    by_mo: dict[str, dict[str, int]] = {}
    for row in rows:
        by_mo.setdefault(str(row['mo']), {})[str(row['flag'])] = int(row['n'])
    return [
        {'mo': mo, 'flags': flags, 'total': sum(flags.values())}
        for mo, flags in sorted(by_mo.items())
    ]


def get_detail(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    mo: str = '',
    flag: str = '',
    page: int = 1,
    page_size: int = 200,
) -> dict[str, Any]:
    where = 'run_id = ?'
    params: list[Any] = [run_id]
    if mo:
        where += ' AND mo = ?'
        params.append(mo)
    if flag:
        where += ' AND flag = ?'
        params.append(flag)
    total = int(conn.execute(
        f'SELECT COUNT(*) FROM audit_detail WHERE {where}', params
    ).fetchone()[0])
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 1000))
    offset = (page - 1) * page_size
    rows = conn.execute(
        f'SELECT mo, object_key, ne_name, flag, mismatch_json, payload_json, detected_date '
        f'FROM audit_detail WHERE {where} ORDER BY mo, flag, object_key LIMIT ? OFFSET ?',
        params + [page_size, offset],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item['mismatches'] = json.loads(item.pop('mismatch_json') or '[]')
        except ValueError:
            item['mismatches'] = []
        try:
            item['payload'] = json.loads(item.pop('payload_json') or '{}')
        except ValueError:
            item['payload'] = {}
        items.append(item)
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'pages': (total + page_size - 1) // page_size if total else 0,
        'items': items,
    }


def get_trend(conn: sqlite3.Connection, *, vendor: str = '', limit: int = 90) -> list[dict[str, Any]]:
    where = 'WHERE vendor = ?' if vendor else ''
    params: list[Any] = [vendor] if vendor else []
    params.append(int(limit))
    rows = conn.execute(
        f'SELECT vendor, run_date, run_id, total_mismatches FROM audit_trend {where} '
        'ORDER BY run_date DESC LIMIT ?',
        params,
    ).fetchall()
    return [dict(row) for row in reversed(rows)]
