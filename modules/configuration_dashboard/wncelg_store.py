"""SQLite snapshot store for Configuration Dashboard WNCELG site split view."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from sync_config import DATABASES_ROOT

_STORE_DIR = os.path.join(DATABASES_ROOT, 'configuration_dashboard')
_STORE_DB = os.path.join(_STORE_DIR, 'wncelg_snapshot.db')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> str:
    return _STORE_DB


def ensure_db_dir() -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(_STORE_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS wncelg_build (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            built_at TEXT NOT NULL,
            mo_class TEXT NOT NULL DEFAULT '',
            group_count INTEGER NOT NULL DEFAULT 0,
            site_count INTEGER NOT NULL DEFAULT 0,
            build_seconds REAL,
            trigger_source TEXT NOT NULL DEFAULT 'scheduled',
            status TEXT NOT NULL DEFAULT 'ok',
            error TEXT NOT NULL DEFAULT '',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            summary_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS wncelg_group (
            dn TEXT PRIMARY KEY,
            instance TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            metadata_site_id TEXT NOT NULL DEFAULT '',
            site_name TEXT NOT NULL DEFAULT '',
            area TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS wncelg_site (
            site_id TEXT PRIMARY KEY,
            metadata_site_id TEXT NOT NULL DEFAULT '',
            site_name TEXT NOT NULL DEFAULT '',
            area TEXT NOT NULL DEFAULT '',
            group_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'no_split',
            instances_json TEXT NOT NULL DEFAULT '[]',
            dns_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_wncelg_group_site ON wncelg_group (site_id);
        CREATE INDEX IF NOT EXISTS idx_wncelg_group_area ON wncelg_group (area);
        CREATE INDEX IF NOT EXISTS idx_wncelg_site_area ON wncelg_site (area);
        CREATE INDEX IF NOT EXISTS idx_wncelg_site_status ON wncelg_site (status);
        """
    )


def replace_snapshot(
    group_rows: list[dict[str, Any]],
    site_rows: list[dict[str, Any]],
    *,
    mo_class: str = '',
    warnings: list[str] | None = None,
    summary: dict[str, Any] | None = None,
    build_seconds: float | None = None,
    trigger_source: str = 'scheduled',
    status: str = 'ok',
    error: str = '',
) -> dict[str, Any]:
    """Replace the full WNCELG snapshot in one transaction."""
    built_at = _utc_now_iso()
    warnings = list(warnings or [])
    summary = dict(summary or {})
    conn = get_connection()
    try:
        conn.execute('BEGIN')
        conn.execute('DELETE FROM wncelg_group')
        conn.execute('DELETE FROM wncelg_site')
        conn.execute('DELETE FROM wncelg_build')
        for row in group_rows:
            conn.execute(
                """
                INSERT INTO wncelg_group (
                    dn, instance, site_id, metadata_site_id, site_name, area
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get('DN') or row.get('dn') or ''),
                    str(row.get('$instance') or row.get('instance') or ''),
                    str(row.get('site_id') or ''),
                    str(row.get('metadata_site_id') or ''),
                    str(row.get('site_name') or ''),
                    str(row.get('area') or ''),
                ),
            )
        for site in site_rows:
            instances = site.get('instances') or []
            dns = site.get('dns') or []
            if isinstance(instances, str):
                instances_json = instances
            else:
                instances_json = json.dumps(list(instances))
            if isinstance(dns, str):
                dns_json = dns
            else:
                dns_json = json.dumps(list(dns))
            conn.execute(
                """
                INSERT INTO wncelg_site (
                    site_id, metadata_site_id, site_name, area,
                    group_count, status, instances_json, dns_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(site.get('site_id') or ''),
                    str(site.get('metadata_site_id') or ''),
                    str(site.get('site_name') or ''),
                    str(site.get('area') or ''),
                    int(site.get('group_count') or 0),
                    str(site.get('status') or 'no_split'),
                    instances_json,
                    dns_json,
                ),
            )
        conn.execute(
            """
            INSERT INTO wncelg_build (
                id, built_at, mo_class, group_count, site_count, build_seconds,
                trigger_source, status, error, warnings_json, summary_json
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                built_at,
                mo_class or '',
                len(group_rows),
                len(site_rows),
                build_seconds,
                trigger_source,
                status,
                error or '',
                json.dumps(warnings),
                json.dumps(summary),
            ),
        )
        conn.commit()
        return get_build_meta() or {
            'built_at': built_at,
            'group_count': len(group_rows),
            'site_count': len(site_rows),
            'status': status,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_failed_build(
    *,
    trigger_source: str,
    error: str,
    build_seconds: float | None = None,
) -> dict[str, Any]:
    """Keep prior rows; update build meta to show the failed attempt."""
    previous = get_build_meta() or {}
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO wncelg_build (
                id, built_at, mo_class, group_count, site_count, build_seconds,
                trigger_source, status, error, warnings_json, summary_json
            ) VALUES (1, ?, ?, ?, ?, ?, ?, 'error', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                built_at = excluded.built_at,
                build_seconds = excluded.build_seconds,
                trigger_source = excluded.trigger_source,
                status = 'error',
                error = excluded.error
            """,
            (
                _utc_now_iso(),
                str(previous.get('mo_class') or ''),
                int(previous.get('group_count') or 0),
                int(previous.get('site_count') or 0),
                build_seconds,
                trigger_source,
                (error or '')[:2000],
                json.dumps(previous.get('warnings') or []),
                json.dumps(previous.get('summary') or {}),
            ),
        )
        conn.commit()
        return get_build_meta() or {}
    finally:
        conn.close()


def get_build_meta() -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM wncelg_build WHERE id = 1').fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data['warnings'] = json.loads(data.pop('warnings_json') or '[]')
        except json.JSONDecodeError:
            data['warnings'] = []
        try:
            data['summary'] = json.loads(data.pop('summary_json') or '{}')
        except json.JSONDecodeError:
            data['summary'] = {}
        # Alias for UI that expects row_count.
        data['row_count'] = int(data.get('site_count') or 0)
        return data
    finally:
        conn.close()


def load_sites() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        raw = conn.execute(
            """
            SELECT site_id, metadata_site_id, site_name, area,
                   group_count, status, instances_json, dns_json
            FROM wncelg_site
            ORDER BY
                CASE status WHEN 'split' THEN 0 ELSE 1 END,
                area COLLATE NOCASE,
                site_name COLLATE NOCASE,
                site_id
            """
        ).fetchall()
    finally:
        conn.close()

    sites: list[dict[str, Any]] = []
    for item in raw:
        try:
            instances = json.loads(item['instances_json'] or '[]')
        except json.JSONDecodeError:
            instances = []
        try:
            dns = json.loads(item['dns_json'] or '[]')
        except json.JSONDecodeError:
            dns = []
        if not isinstance(instances, list):
            instances = []
        if not isinstance(dns, list):
            dns = []
        sites.append({
            'site_id': item['site_id'],
            'metadata_site_id': item['metadata_site_id'],
            'site_name': item['site_name'],
            'area': item['area'],
            'group_count': int(item['group_count'] or 0),
            'status': item['status'],
            'instances': instances,
            'dns': dns,
            'instances_csv': ','.join(str(v) for v in instances),
            'dns_csv': ' | '.join(str(v) for v in dns),
        })
    return sites


def has_snapshot() -> bool:
    meta = get_build_meta()
    return bool(meta and int(meta.get('site_count') or 0) > 0)


def list_snapshot_areas() -> list[dict[str, str | int]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT area,
                   COUNT(*) AS site_count,
                   SUM(CASE WHEN status = 'split' THEN 1 ELSE 0 END) AS split_count
            FROM wncelg_site
            WHERE TRIM(COALESCE(area, '')) != ''
            GROUP BY area
            ORDER BY area COLLATE NOCASE
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            'area': str(row['area'] or ''),
            'site_count': int(row['site_count'] or 0),
            'split_count': int(row['split_count'] or 0),
        }
        for row in rows
        if str(row['area'] or '').strip()
    ]
