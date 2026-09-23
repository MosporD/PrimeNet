"""SQLite snapshot store for Adjacency GIS (Nokia ADCE + Huawei G2GNCELL)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from sync_config import DATABASES_ROOT

_STORE_DIR = os.path.join(DATABASES_ROOT, 'adjacency_gis')
_STORE_DB = os.path.join(_STORE_DIR, 'adjacency_snapshot.db')

VENDORS = ('nokia', 'huawei')


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
        CREATE TABLE IF NOT EXISTS adj_build (
            vendor TEXT PRIMARY KEY,
            built_at TEXT NOT NULL,
            sector_count INTEGER NOT NULL DEFAULT 0,
            edge_count INTEGER NOT NULL DEFAULT 0,
            build_seconds REAL,
            trigger_source TEXT NOT NULL DEFAULT 'scheduled',
            status TEXT NOT NULL DEFAULT 'ok',
            error TEXT NOT NULL DEFAULT '',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            summary_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS adj_sector (
            dn TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'nokia',
            bsc_id TEXT NOT NULL DEFAULT '',
            bcf_id TEXT NOT NULL DEFAULT '',
            instance TEXT NOT NULL DEFAULT '',
            segment_name TEXT NOT NULL DEFAULT '',
            cell_name TEXT NOT NULL DEFAULT '',
            cell_id INTEGER,
            bcch INTEGER,
            trx_dn TEXT NOT NULL DEFAULT '',
            admin_state TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (vendor, dn)
        );

        CREATE TABLE IF NOT EXISTS adj_edge (
            dn TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'nokia',
            source_dn TEXT NOT NULL,
            adj_ci INTEGER NOT NULL,
            adj_lac INTEGER,
            adj_mcc INTEGER,
            adj_mnc INTEGER,
            bcch_frequency INTEGER,
            PRIMARY KEY (vendor, dn)
        );

        CREATE INDEX IF NOT EXISTS idx_adj_sector_bsc ON adj_sector (bsc_id);
        CREATE INDEX IF NOT EXISTS idx_adj_sector_vendor ON adj_sector (vendor);
        CREATE INDEX IF NOT EXISTS idx_adj_sector_cell_name ON adj_sector (cell_name);
        CREATE INDEX IF NOT EXISTS idx_adj_sector_cell_id ON adj_sector (cell_id);
        CREATE INDEX IF NOT EXISTS idx_adj_edge_source ON adj_edge (source_dn);
        CREATE INDEX IF NOT EXISTS idx_adj_edge_vendor ON adj_edge (vendor);
        CREATE INDEX IF NOT EXISTS idx_adj_edge_ci ON adj_edge (adj_ci);
        """
    )
    _migrate_legacy_single_build(conn)
    _ensure_vendor_columns(conn)


def _ensure_vendor_columns(conn: sqlite3.Connection) -> None:
    """Add vendor columns to older single-vendor DBs."""
    for table in ('adj_sector', 'adj_edge'):
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        if 'vendor' not in cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN vendor TEXT NOT NULL DEFAULT 'nokia'"
            )
    conn.commit()


def _migrate_legacy_single_build(conn: sqlite3.Connection) -> None:
    """Convert old adj_build(id=1) row into vendor-keyed rows if needed."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(adj_build)').fetchall()}
    if not cols:
        return
    if 'vendor' in cols and 'id' not in cols:
        return
    if 'id' in cols:
        row = conn.execute('SELECT * FROM adj_build WHERE id = 1').fetchone()
        if row:
            data = dict(row)
            vendor = str(data.get('vendor') or 'nokia')
            conn.execute('DELETE FROM adj_build')
            # Recreate table without id if needed — simplest: insert into new shape
            # If schema still has id PK, rebuild table.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS adj_build_v2 (
                    vendor TEXT PRIMARY KEY,
                    built_at TEXT NOT NULL,
                    sector_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    build_seconds REAL,
                    trigger_source TEXT NOT NULL DEFAULT 'scheduled',
                    status TEXT NOT NULL DEFAULT 'ok',
                    error TEXT NOT NULL DEFAULT '',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    summary_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO adj_build_v2 (
                    vendor, built_at, sector_count, edge_count, build_seconds,
                    trigger_source, status, error, warnings_json, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vendor,
                    data.get('built_at') or _utc_now_iso(),
                    int(data.get('sector_count') or 0),
                    int(data.get('edge_count') or 0),
                    data.get('build_seconds'),
                    data.get('trigger_source') or 'scheduled',
                    data.get('status') or 'ok',
                    data.get('error') or '',
                    data.get('warnings_json') or '[]',
                    data.get('summary_json') or '{}',
                ),
            )
            conn.execute('DROP TABLE adj_build')
            conn.execute('ALTER TABLE adj_build_v2 RENAME TO adj_build')
            conn.commit()


def replace_vendor_snapshot(
    vendor: str,
    sectors: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    warnings: list[str] | None = None,
    summary: dict[str, Any] | None = None,
    build_seconds: float | None = None,
    trigger_source: str = 'scheduled',
    status: str = 'ok',
    error: str = '',
) -> dict[str, Any]:
    """Replace one vendor's sectors/edges; leave the other vendor intact."""
    vendor = (vendor or 'nokia').strip().lower()
    if vendor not in VENDORS:
        raise ValueError(f'Unsupported vendor: {vendor}')
    built_at = _utc_now_iso()
    warnings = list(warnings or [])
    summary = dict(summary or {})
    conn = get_connection()
    try:
        conn.execute('BEGIN')
        conn.execute('DELETE FROM adj_edge WHERE vendor = ?', (vendor,))
        conn.execute('DELETE FROM adj_sector WHERE vendor = ?', (vendor,))
        conn.execute('DELETE FROM adj_build WHERE vendor = ?', (vendor,))
        for row in sectors:
            conn.execute(
                """
                INSERT INTO adj_sector (
                    dn, vendor, bsc_id, bcf_id, instance, segment_name, cell_name,
                    cell_id, bcch, trx_dn, admin_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get('dn') or ''),
                    vendor,
                    str(row.get('bsc_id') or ''),
                    str(row.get('bcf_id') or ''),
                    str(row.get('instance') or ''),
                    str(row.get('segment_name') or ''),
                    str(row.get('cell_name') or ''),
                    row.get('cell_id'),
                    row.get('bcch'),
                    str(row.get('trx_dn') or ''),
                    str(row.get('admin_state') or ''),
                ),
            )
        for row in edges:
            conn.execute(
                """
                INSERT INTO adj_edge (
                    dn, vendor, source_dn, adj_ci, adj_lac, adj_mcc, adj_mnc, bcch_frequency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get('dn') or ''),
                    vendor,
                    str(row.get('bts_dn') or row.get('source_dn') or ''),
                    int(row['adj_ci']) if row.get('adj_ci') is not None else -1,
                    row.get('adj_lac'),
                    row.get('adj_mcc'),
                    row.get('adj_mnc'),
                    row.get('bcch_frequency'),
                ),
            )
        # Drop edges with missing CI sentinel
        conn.execute('DELETE FROM adj_edge WHERE vendor = ? AND adj_ci < 0', (vendor,))
        conn.execute(
            """
            INSERT INTO adj_build (
                vendor, built_at, sector_count, edge_count, build_seconds,
                trigger_source, status, error, warnings_json, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor,
                built_at,
                len(sectors),
                len(edges),
                build_seconds,
                trigger_source,
                status,
                error or '',
                json.dumps(warnings),
                json.dumps(summary),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_build_meta(vendor) or {
        'vendor': vendor,
        'built_at': built_at,
        'sector_count': len(sectors),
        'edge_count': len(edges),
        'status': status,
    }


def replace_snapshot(
    sectors: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    warnings: list[str] | None = None,
    summary: dict[str, Any] | None = None,
    build_seconds: float | None = None,
    trigger_source: str = 'scheduled',
    status: str = 'ok',
    error: str = '',
    vendor: str = 'nokia',
) -> dict[str, Any]:
    """Back-compat wrapper — replaces one vendor snapshot."""
    return replace_vendor_snapshot(
        vendor,
        sectors,
        edges,
        warnings=warnings,
        summary=summary,
        build_seconds=build_seconds,
        trigger_source=trigger_source,
        status=status,
        error=error,
    )


def _decode_meta_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    try:
        data['warnings'] = json.loads(data.pop('warnings_json') or '[]')
    except json.JSONDecodeError:
        data['warnings'] = []
        data.pop('warnings_json', None)
    try:
        data['summary'] = json.loads(data.pop('summary_json') or '{}')
    except json.JSONDecodeError:
        data['summary'] = {}
        data.pop('summary_json', None)
    return data


def get_build_meta(vendor: str | None = None) -> dict[str, Any] | None:
    """
    Return one vendor's build meta, or a combined summary when vendor is None.
    """
    conn = get_connection()
    try:
        if vendor:
            row = conn.execute(
                'SELECT * FROM adj_build WHERE vendor = ?',
                (vendor.strip().lower(),),
            ).fetchone()
            return _decode_meta_row(row) if row else None

        rows = conn.execute('SELECT * FROM adj_build ORDER BY vendor').fetchall()
        if not rows:
            return None
        metas = [_decode_meta_row(r) for r in rows]
        sector_count = sum(int(m.get('sector_count') or 0) for m in metas)
        edge_count = sum(int(m.get('edge_count') or 0) for m in metas)
        warnings: list[str] = []
        for m in metas:
            warnings.extend(m.get('warnings') or [])
        statuses = {str(m.get('status') or '') for m in metas}
        status = 'ok' if statuses == {'ok'} else ('error' if 'error' in statuses else 'mixed')
        latest = max((m.get('built_at') or '' for m in metas), default='')
        return {
            'vendor': 'all',
            'built_at': latest,
            'sector_count': sector_count,
            'edge_count': edge_count,
            'status': status,
            'warnings': warnings,
            'summary': {m['vendor']: m.get('summary') or {} for m in metas},
            'by_vendor': {m['vendor']: m for m in metas},
        }
    finally:
        conn.close()


def load_sectors(vendor: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if vendor and vendor.strip().lower() not in ('all', '*', ''):
            rows = conn.execute(
                'SELECT * FROM adj_sector WHERE vendor = ?',
                (vendor.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM adj_sector').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_edges(vendor: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if vendor and vendor.strip().lower() not in ('all', '*', ''):
            rows = conn.execute(
                'SELECT * FROM adj_edge WHERE vendor = ?',
                (vendor.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM adj_edge').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_bsc_ids(vendor: str | None = None) -> list[str]:
    conn = get_connection()
    try:
        if vendor and vendor.strip().lower() not in ('all', '*', ''):
            rows = conn.execute(
                """
                SELECT DISTINCT bsc_id FROM adj_sector
                WHERE vendor = ? AND TRIM(bsc_id) != ''
                ORDER BY bsc_id
                """,
                (vendor.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT bsc_id FROM adj_sector
                WHERE TRIM(bsc_id) != ''
                ORDER BY bsc_id
                """
            ).fetchall()
        return [str(r[0]) for r in rows if r[0]]
    finally:
        conn.close()
