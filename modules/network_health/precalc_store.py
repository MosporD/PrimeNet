"""SQLite store for precomputed Network Health KPI tables (daily batch job)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from sync_config import DATABASES_ROOT

from . import config as cfg

_PRECALC_DIR = os.path.join(DATABASES_ROOT, "network_health")
_PRECALC_DB = os.path.join(_PRECALC_DIR, "precalc.db")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> str:
    return _PRECALC_DB


def ensure_db_dir() -> None:
    os.makedirs(_PRECALC_DIR, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(_PRECALC_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS nh_build (
            vendor TEXT NOT NULL,
            rat TEXT NOT NULL,
            built_at TEXT NOT NULL,
            pm_fingerprint TEXT NOT NULL,
            total_kpi_count INTEGER NOT NULL DEFAULT 0,
            precomputed_kpis_json TEXT NOT NULL DEFAULT '[]',
            row_count INTEGER NOT NULL DEFAULT 0,
            build_seconds REAL,
            PRIMARY KEY (vendor, rat)
        );

        CREATE TABLE IF NOT EXISTS nh_cell_row (
            vendor TEXT NOT NULL,
            rat TEXT NOT NULL,
            kpi TEXT NOT NULL,
            cell_name TEXT NOT NULL,
            pre REAL,
            post REAL,
            delta REAL,
            area TEXT,
            cluster INTEGER,
            rnc TEXT,
            cell_vendor TEXT,
            PRIMARY KEY (vendor, rat, kpi, cell_name)
        );

        CREATE INDEX IF NOT EXISTS idx_nh_cell_vendor_rat_kpi
            ON nh_cell_row (vendor, rat, kpi);
        """
    )


def pm_fingerprint(vendor: str, rat: str) -> str:
    """Fingerprint PM daily DB files for vendor + RAT (invalidates store when PM reloads)."""
    import hashlib

    from modules.son_analytics.pm_helpers import PM_DATA_SCOPE, vendor_pm_sources

    pm_tech = cfg.pm_technology_for_rat(rat)
    parts: list[str] = []
    for _vlabel, db_path, table in vendor_pm_sources(vendor, pm_tech, PM_DATA_SCOPE):
        if not db_path or not table:
            continue
        if os.path.isfile(db_path):
            # Use file size (not mtime): PM sync often touches mtime without changing data.
            parts.append(f"{db_path}|{table}|{os.path.getsize(db_path)}")
        else:
            parts.append(f"{db_path}|{table}|missing")
    blob = "\n".join(sorted(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def get_build_meta(vendor: str, rat: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM nh_build WHERE vendor = ? AND rat = ?",
            (vendor, rat),
        ).fetchone()
        if not row:
            return None
        meta = dict(row)
        meta["precomputed_kpis"] = json.loads(meta.pop("precomputed_kpis_json") or "[]")
        meta["is_stale"] = meta.get("pm_fingerprint") != pm_fingerprint(vendor, rat)
        return meta
    finally:
        conn.close()


def _row_from_db(row: sqlite3.Row) -> dict:
    return {
        "cell_name": row["cell_name"],
        "pre": row["pre"],
        "post": row["post"],
        "delta": row["delta"],
        "area": row["area"],
        "cluster": row["cluster"],
        "rnc": row["rnc"],
        "vendor": row["cell_vendor"],
    }


def load_precalc_meta(vendor: str, rat: str, *, allow_stale: bool = True) -> dict | None:
    """Build metadata only (no cell rows) — fast path for UI init."""
    meta = get_build_meta(vendor, rat)
    if not meta:
        return None
    is_stale = bool(meta.get("is_stale"))
    if is_stale and not allow_stale:
        return None
    row_count = int(meta.get("row_count") or 0)
    return {
        "precomputed_kpis": list(meta.get("precomputed_kpis") or []),
        "total_kpi_count": int(meta.get("total_kpi_count") or 0),
        "built_at": meta.get("built_at"),
        "row_count": row_count,
        "pm_fingerprint": meta.get("pm_fingerprint"),
        "is_stale": is_stale,
        "has_rows": row_count > 0,
    }


def load_kpi_rows(
    vendor: str,
    rat: str,
    kpi: str,
    *,
    allow_stale: bool = True,
    area: str = "",
    cluster: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """One KPI table from SQLite: cell | pre | post | delta (pre=7-day avg, post=latest)."""
    meta = get_build_meta(vendor, rat)
    if not meta:
        return []
    is_stale = bool(meta.get("is_stale"))
    if is_stale and not allow_stale:
        return []

    sql = """
        SELECT cell_name, pre, post, delta, area, cluster, rnc, cell_vendor
        FROM nh_cell_row
        WHERE vendor = ? AND rat = ? AND kpi = ?
    """
    params: list[object] = [vendor, rat, kpi]
    if area:
        sql += " AND area = ?"
        params.append(area)
    if cluster is not None:
        sql += " AND cluster = ?"
        params.append(cluster)
    sql += " ORDER BY cell_name"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))

    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        return [_row_from_db(row) for row in cur]
    finally:
        conn.close()


def load_payload(vendor: str, rat: str, *, allow_stale: bool = True) -> dict | None:
    """Load all KPI tables (slow; avoid in web requests — use load_precalc_meta + load_kpi_rows)."""
    meta = load_precalc_meta(vendor, rat, allow_stale=allow_stale)
    if not meta:
        return None

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT kpi, cell_name, pre, post, delta, area, cluster, rnc, cell_vendor
            FROM nh_cell_row
            WHERE vendor = ? AND rat = ?
            ORDER BY kpi, cell_name
            """,
            (vendor, rat),
        )
        tables: dict[str, list[dict]] = {}
        for row in cur:
            kpi = row["kpi"]
            tables.setdefault(kpi, []).append(_row_from_db(row))
        return {
            "tables": tables,
            "precomputed_kpis": meta.get("precomputed_kpis") or list(tables.keys()),
            "total_kpi_count": meta.get("total_kpi_count") or 0,
            "built_at": meta.get("built_at"),
            "row_count": meta.get("row_count") or 0,
            "pm_fingerprint": meta.get("pm_fingerprint"),
            "is_stale": meta.get("is_stale"),
        }
    finally:
        conn.close()


def save_payload(
    vendor: str,
    rat: str,
    tables: dict[str, list[dict]],
    *,
    precomputed_kpis: list[str],
    total_kpi_count: int,
    fingerprint: str,
    build_seconds: float | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM nh_cell_row WHERE vendor = ? AND rat = ?", (vendor, rat))
        insert_rows: list[tuple] = []
        for kpi, rows in tables.items():
            for r in rows:
                insert_rows.append(
                    (
                        vendor,
                        rat,
                        kpi,
                        r.get("cell_name"),
                        r.get("pre"),
                        r.get("post"),
                        r.get("delta"),
                        r.get("area"),
                        r.get("cluster"),
                        r.get("rnc"),
                        r.get("vendor"),
                    )
                )
        if insert_rows:
            conn.executemany(
                """
                INSERT INTO nh_cell_row (
                    vendor, rat, kpi, cell_name, pre, post, delta,
                    area, cluster, rnc, cell_vendor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO nh_build (
                vendor, rat, built_at, pm_fingerprint, total_kpi_count,
                precomputed_kpis_json, row_count, build_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor,
                rat,
                _utc_now_iso(),
                fingerprint,
                int(total_kpi_count),
                json.dumps(precomputed_kpis),
                len(insert_rows),
                build_seconds,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_built_combos() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT vendor, rat, built_at, total_kpi_count, row_count, build_seconds FROM nh_build ORDER BY vendor, rat"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
