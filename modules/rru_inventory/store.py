"""SQLite snapshot store for Radio Hardware Inventory Report (RMOD_R)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from sync_config import DATABASES_ROOT

_STORE_DIR = os.path.join(DATABASES_ROOT, 'rru_inventory')
_STORE_DB = os.path.join(_STORE_DIR, 'rmod_snapshot.db')


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
        CREATE TABLE IF NOT EXISTS rmod_build (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            built_at TEXT NOT NULL,
            mo_class TEXT NOT NULL DEFAULT '',
            row_count INTEGER NOT NULL DEFAULT 0,
            build_seconds REAL,
            trigger_source TEXT NOT NULL DEFAULT 'scheduled',
            status TEXT NOT NULL DEFAULT 'ok',
            error TEXT NOT NULL DEFAULT '',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            summary_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS rmod_row (
            dn TEXT PRIMARY KEY,
            instance TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            metadata_site_id TEXT NOT NULL DEFAULT '',
            site_name TEXT NOT NULL DEFAULT '',
            area TEXT NOT NULL DEFAULT '',
            product_name TEXT NOT NULL DEFAULT '',
            operational_state TEXT NOT NULL DEFAULT '',
            config_dn TEXT NOT NULL DEFAULT '',
            techs_json TEXT NOT NULL DEFAULT '[]',
            unused INTEGER NOT NULL DEFAULT 0,
            multi_rat INTEGER NOT NULL DEFAULT 0,
            active_gsm TEXT NOT NULL DEFAULT '',
            active_wcdma TEXT NOT NULL DEFAULT '',
            active_lte TEXT NOT NULL DEFAULT '',
            active_nr TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_rmod_row_area ON rmod_row (area);
        CREATE INDEX IF NOT EXISTS idx_rmod_row_product ON rmod_row (product_name);
        """
    )


def replace_snapshot(
    rows: list[dict[str, Any]],
    *,
    mo_class: str = '',
    warnings: list[str] | None = None,
    summary: dict[str, Any] | None = None,
    build_seconds: float | None = None,
    trigger_source: str = 'scheduled',
    status: str = 'ok',
    error: str = '',
) -> dict[str, Any]:
    """Replace the full network snapshot in one transaction."""
    built_at = _utc_now_iso()
    warnings = list(warnings or [])
    summary = dict(summary or {})
    conn = get_connection()
    try:
        conn.execute('BEGIN')
        conn.execute('DELETE FROM rmod_row')
        conn.execute('DELETE FROM rmod_build')
        for row in rows:
            techs = row.get('techs') or []
            if isinstance(techs, str):
                techs_json = techs
            else:
                techs_json = json.dumps(list(techs))
            conn.execute(
                """
                INSERT INTO rmod_row (
                    dn, instance, site_id, metadata_site_id, site_name, area,
                    product_name, operational_state, config_dn, techs_json,
                    unused, multi_rat, active_gsm, active_wcdma, active_lte, active_nr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get('DN') or row.get('dn') or ''),
                    str(row.get('$instance') or row.get('instance') or ''),
                    str(row.get('site_id') or ''),
                    str(row.get('metadata_site_id') or ''),
                    str(row.get('site_name') or ''),
                    str(row.get('area') or ''),
                    str(row.get('productName') or row.get('product_name') or ''),
                    str(row.get('operationalState') or row.get('operational_state') or ''),
                    str(row.get('configDN') or row.get('config_dn') or ''),
                    techs_json,
                    1 if row.get('unused') else 0,
                    1 if row.get('multi_rat') else 0,
                    str(row.get('activeGsmCellsList') or row.get('active_gsm') or ''),
                    str(row.get('activeWcdmaCellsList') or row.get('active_wcdma') or ''),
                    str(row.get('activeLteCellsList') or row.get('active_lte') or ''),
                    str(row.get('activeNrCellsList') or row.get('active_nr') or ''),
                ),
            )
        conn.execute(
            """
            INSERT INTO rmod_build (
                id, built_at, mo_class, row_count, build_seconds, trigger_source,
                status, error, warnings_json, summary_json
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                built_at,
                mo_class or '',
                len(rows),
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
            'row_count': len(rows),
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
            INSERT INTO rmod_build (
                id, built_at, mo_class, row_count, build_seconds, trigger_source,
                status, error, warnings_json, summary_json
            ) VALUES (1, ?, ?, ?, ?, ?, 'error', ?, ?, ?)
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
                int(previous.get('row_count') or 0),
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
        row = conn.execute('SELECT * FROM rmod_build WHERE id = 1').fetchone()
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
        return data
    finally:
        conn.close()


def load_rows(*, area: str = '') -> list[dict[str, Any]]:
    """Load enriched RMOD rows from the latest snapshot (optional area filter)."""
    from modules.rru_inventory.logic import _area_key, UNUSED_TECH

    conn = get_connection()
    try:
        raw = conn.execute(
            """
            SELECT dn, instance, site_id, metadata_site_id, site_name, area,
                   product_name, operational_state, config_dn, techs_json,
                   unused, multi_rat, active_gsm, active_wcdma, active_lte, active_nr
            FROM rmod_row
            ORDER BY area, site_name, product_name, dn
            """
        ).fetchall()
    finally:
        conn.close()

    want = (area or '').strip()
    want_key = _area_key(want) if want and want.lower() not in ('all', '*') else ''

    rows: list[dict[str, Any]] = []
    for item in raw:
        area_val = str(item['area'] or '')
        if want_key and _area_key(area_val) != want_key:
            continue
        try:
            techs = json.loads(item['techs_json'] or '[]')
        except json.JSONDecodeError:
            techs = [UNUSED_TECH]
        if not isinstance(techs, list) or not techs:
            techs = [UNUSED_TECH]
        rows.append({
            'DN': item['dn'],
            '$instance': item['instance'],
            'site_id': item['site_id'],
            'metadata_site_id': item['metadata_site_id'],
            'site_name': item['site_name'],
            'area': area_val,
            'productName': item['product_name'],
            'operationalState': item['operational_state'],
            'configDN': item['config_dn'],
            'techs': techs,
            'unused': bool(item['unused']),
            'multi_rat': bool(item['multi_rat']),
            'activeGsmCellsList': item['active_gsm'],
            'activeWcdmaCellsList': item['active_wcdma'],
            'activeLteCellsList': item['active_lte'],
            'activeNrCellsList': item['active_nr'],
        })
    return rows


def has_snapshot() -> bool:
    meta = get_build_meta()
    return bool(meta and int(meta.get('row_count') or 0) > 0)


def list_snapshot_areas() -> list[dict[str, str | int]]:
    """Distinct areas from the local snapshot only (no NetAct / inventory discovery)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT area,
                   COUNT(*) AS rru_count,
                   COUNT(DISTINCT site_id) AS site_count
            FROM rmod_row
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
            'rru_count': int(row['rru_count'] or 0),
        }
        for row in rows
        if str(row['area'] or '').strip()
    ]
