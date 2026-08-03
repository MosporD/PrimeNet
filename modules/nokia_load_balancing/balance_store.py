"""SQLite store for daily Network Balance sector snapshots."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from sync_config import NETWORK_BALANCE_DB

from db.runtime import connect_network_balance, execute_query

from . import config
from .rules import highest_lowest_layer, normalize_throughput

_SCHEMA_VERSION = 1


def _normalize_sector(value) -> str:
    return str(value or "").strip().replace("-", "_").upper()


def _row_throughput(row) -> dict[str, float | None]:
    raw = {}
    for layer, col in config.THROUGHPUT_COLUMNS.items():
        if col not in row.index:
            continue
        val = row.get(col)
        if pd.isna(val):
            continue
        try:
            raw[layer] = float(val)
        except (TypeError, ValueError):
            continue
    return normalize_throughput(raw)


def _json_safe(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _row_to_json(row: pd.Series) -> str:
    payload = {str(k): _json_safe(v) for k, v in row.items()}
    return json.dumps(payload, ensure_ascii=False)


def init_schema(conn=None) -> None:
    own = conn is None
    Path(NETWORK_BALANCE_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = conn or connect_network_balance()
    try:
        execute_query(
            conn,
            """
            CREATE TABLE IF NOT EXISTS balance_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        )
        execute_query(
            conn,
            """
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_mtime REAL,
                ingested_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(vendor, snapshot_date)
            )
            """,
        )
        execute_query(
            conn,
            """
            CREATE TABLE IF NOT EXISTS balance_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                sector_id TEXT NOT NULL,
                balancing_status TEXT,
                throughput_l18 REAL,
                throughput_l21 REAL,
                throughput_l9 REAL,
                throughput_l18plus REAL,
                highest_layer TEXT,
                lowest_layer TEXT,
                row_json TEXT NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES balance_snapshots(id) ON DELETE CASCADE,
                UNIQUE(snapshot_id, sector_id)
            )
            """,
        )
        execute_query(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_balance_sectors_snapshot ON balance_sectors(snapshot_id)",
        )
        execute_query(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_balance_sectors_sector ON balance_sectors(sector_id)",
        )
        execute_query(
            conn,
            """
            INSERT INTO balance_meta(key, value) VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(_SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def _snapshot_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def snapshot_needs_update(vendor: str, snapshot_date: date, source_path: Path, conn=None) -> bool:
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    try:
        row = execute_query(
            conn,
            """
            SELECT source_mtime, source_file FROM balance_snapshots
            WHERE vendor = ? AND snapshot_date = ?
            """,
            (vendor, snapshot_date.isoformat()),
        ).fetchone()
        if row is None:
            return True
        current_mtime = _snapshot_mtime(source_path)
        if current_mtime and float(row["source_mtime"] or 0) >= current_mtime:
            return False
        return True
    finally:
        if own:
            conn.close()


def ingest_csv_file(
    path: Path,
    *,
    vendor: str,
    snapshot_date: date,
    conn=None,
) -> dict[str, Any]:
    """Load one vendor CSV into SQLite. Returns summary dict."""
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()

    ingested_at = datetime.now().isoformat(timespec="seconds")
    mtime = _snapshot_mtime(path)
    vendor_key = vendor.lower()

    try:
        execute_query(
            conn,
            "DELETE FROM balance_snapshots WHERE vendor = ? AND snapshot_date = ?",
            (vendor_key, snapshot_date.isoformat()),
        )
        cur = execute_query(
            conn,
            """
            INSERT INTO balance_snapshots
                (vendor, snapshot_date, source_file, source_mtime, ingested_at, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vendor_key, snapshot_date.isoformat(), str(path), mtime, ingested_at, 0),
        )
        snapshot_id = cur.lastrowid

        rows_by_sector: dict[str, tuple] = {}
        for _, row in df.iterrows():
            sector_raw = row.get(config.SECTOR_COLUMN)
            sector_id = _normalize_sector(sector_raw)
            if not sector_id:
                continue
            throughput = _row_throughput(row)
            highest, lowest = highest_lowest_layer(throughput)
            status = str(row.get(config.STATUS_COLUMN) or "").strip().upper() or None
            rows_by_sector[sector_id] = (
                snapshot_id,
                sector_id,
                status,
                throughput.get("L18"),
                throughput.get("L21"),
                throughput.get("L9"),
                throughput.get("L18+"),
                highest,
                lowest,
                _row_to_json(row),
            )

        rows_to_insert = list(rows_by_sector.values())
        if rows_to_insert:
            conn.executemany(
                """
                INSERT INTO balance_sectors (
                    snapshot_id, sector_id, balancing_status,
                    throughput_l18, throughput_l21, throughput_l9, throughput_l18plus,
                    highest_layer, lowest_layer, row_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )

        execute_query(
            conn,
            "UPDATE balance_snapshots SET row_count = ? WHERE id = ?",
            (len(rows_to_insert), snapshot_id),
        )
        conn.commit()
        return {
            "vendor": vendor_key,
            "snapshot_date": snapshot_date.isoformat(),
            "source_file": str(path),
            "row_count": len(rows_to_insert),
            "ingested_at": ingested_at,
            "skipped": False,
        }
    finally:
        if own:
            conn.close()


def find_snapshot(
    vendor: str,
    target_date: date | None = None,
    *,
    lookback_days: int = 7,
    conn=None,
) -> dict[str, Any] | None:
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    vendor_key = vendor.lower()
    start = target_date or date.today()

    try:
        for days_back in range(max(1, lookback_days)):
            candidate = start - timedelta(days=days_back)
            row = execute_query(
                conn,
                """
                SELECT id, vendor, snapshot_date, source_file, ingested_at, row_count
                FROM balance_snapshots
                WHERE vendor = ? AND snapshot_date = ?
                """,
                (vendor_key, candidate.isoformat()),
            ).fetchone()
            if row:
                return dict(row)
        return None
    finally:
        if own:
            conn.close()


def list_sectors_for_snapshot(
    snapshot_id: int,
    *,
    status_filter: str | None = None,
    conn=None,
) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    try:
        sql = """
            SELECT sector_id, balancing_status,
                   throughput_l18, throughput_l21, throughput_l9, throughput_l18plus,
                   highest_layer, lowest_layer, row_json
            FROM balance_sectors
            WHERE snapshot_id = ?
        """
        params: list[Any] = [snapshot_id]
        if status_filter:
            sql += " AND balancing_status = ?"
            params.append(status_filter.upper())
        sql += " ORDER BY sector_id"
        rows = execute_query(conn, sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            throughput = normalize_throughput_from_db(row)
            out.append({
                "sector_id": row["sector_id"],
                "throughput": throughput,
                "highest_layer": row["highest_layer"],
                "lowest_layer": row["lowest_layer"],
                "balancing_status": row["balancing_status"],
            })
        return out
    finally:
        if own:
            conn.close()


def normalize_throughput_from_db(row) -> dict[str, float | None]:
    return {
        "L18": row["throughput_l18"],
        "L21": row["throughput_l21"],
        "L9": row["throughput_l9"],
        "L18+": row["throughput_l18plus"],
    }


def get_sectors_from_db(
    sector_ids: list[str],
    vendor: str,
    target_date: date | None = None,
    *,
    lookback_days: int = 7,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    snapshot = find_snapshot(vendor, target_date, lookback_days=lookback_days)
    if not snapshot:
        return [], ["No Network Balance snapshot in SQLite for this date/vendor."], None

    warnings: list[str] = []
    if target_date and snapshot["snapshot_date"] != target_date.isoformat():
        warnings.append(
            f"Using SQLite snapshot from {snapshot['snapshot_date']} "
            f"(requested {target_date.isoformat()})."
        )

    all_rows = {
        row["sector_id"]: row
        for row in list_sectors_for_snapshot(int(snapshot["id"]))
    }
    sectors: list[dict[str, Any]] = []
    for sector_id in sector_ids:
        row = all_rows.get(sector_id)
        if not row:
            warnings.append(f"Sector {sector_id} not found in SQLite snapshot.")
            continue
        if not row.get("highest_layer") or not row.get("lowest_layer"):
            warnings.append(
                f"Sector {sector_id}: need at least {config.MIN_ACTIVE_LAYERS} layers with throughput > 0."
            )
            continue
        sectors.append({
            "sector_id": sector_id,
            "throughput": row["throughput"],
        })

    source = {
        "source": "sqlite",
        "source_file": snapshot.get("source_file"),
        "snapshot_date": snapshot.get("snapshot_date"),
        "ingested_at": snapshot.get("ingested_at"),
    }
    return sectors, warnings, source


def list_nok_sectors_from_db(
    vendor: str,
    target_date: date | None = None,
    *,
    lookback_days: int = 7,
) -> dict[str, Any]:
    snapshot = find_snapshot(vendor, target_date, lookback_days=lookback_days)
    if not snapshot:
        return {
            "success": False,
            "sectors": [],
            "source": "sqlite",
            "errors": ["No Network Balance snapshot in SQLite. Run ingest first."],
            "warnings": [],
        }

    sectors = list_sectors_for_snapshot(
        int(snapshot["id"]),
        status_filter=config.NOK_STATUS_VALUE,
    )
    warnings: list[str] = []
    if target_date and snapshot["snapshot_date"] != target_date.isoformat():
        warnings.append(
            f"Using SQLite snapshot from {snapshot['snapshot_date']} "
            f"(requested {target_date.isoformat()})."
        )

    return {
        "success": True,
        "sectors": sectors,
        "source": "sqlite",
        "source_file": snapshot.get("source_file"),
        "source_date": snapshot.get("snapshot_date"),
        "ingested_at": snapshot.get("ingested_at"),
        "row_count": snapshot.get("row_count"),
        "warnings": warnings,
        "errors": [],
    }


def recent_snapshots(limit: int = 14, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    try:
        rows = execute_query(
            conn,
            """
            SELECT vendor, snapshot_date, source_file, ingested_at, row_count
            FROM balance_snapshots
            ORDER BY snapshot_date DESC, vendor ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def list_snapshots_in_range(
    start_date: date,
    end_date: date,
    *,
    vendor: str | None = None,
    conn=None,
) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    start = min(start_date, end_date)
    end = max(start_date, end_date)
    try:
        sql = """
            SELECT vendor, snapshot_date, source_file, ingested_at, row_count
            FROM balance_snapshots
            WHERE snapshot_date >= ? AND snapshot_date <= ?
        """
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if vendor:
            sql += " AND vendor = ?"
            params.append(vendor.lower())
        sql += " ORDER BY snapshot_date DESC, vendor ASC"
        rows = execute_query(conn, sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def snapshot_inventory(conn=None) -> dict[str, Any]:
    """Summary of ingested snapshots per vendor."""
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    try:
        rows = execute_query(
            conn,
            """
            SELECT vendor,
                   COUNT(*) AS snapshot_count,
                   MIN(snapshot_date) AS first_date,
                   MAX(snapshot_date) AS last_date,
                   SUM(row_count) AS total_rows
            FROM balance_snapshots
            GROUP BY vendor
            ORDER BY vendor ASC
            """,
        ).fetchall()
        return {
            "vendors": [dict(r) for r in rows],
            "db_path": NETWORK_BALANCE_DB,
        }
    finally:
        if own:
            conn.close()


def daily_status_summary(
    start_date: date,
    end_date: date,
    *,
    vendor: str | None = None,
    conn=None,
) -> list[dict[str, Any]]:
    """Count sectors by balancing status for each vendor/day in range."""
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    start = min(start_date, end_date)
    end = max(start_date, end_date)
    try:
        sql = """
            SELECT s.snapshot_date,
                   s.vendor,
                   COALESCE(bs.balancing_status, 'UNKNOWN') AS balancing_status,
                   COUNT(*) AS sector_count
            FROM balance_sectors bs
            JOIN balance_snapshots s ON s.id = bs.snapshot_id
            WHERE s.snapshot_date >= ? AND s.snapshot_date <= ?
        """
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if vendor:
            sql += " AND s.vendor = ?"
            params.append(vendor.lower())
        sql += """
            GROUP BY s.snapshot_date, s.vendor, COALESCE(bs.balancing_status, 'UNKNOWN')
            ORDER BY s.snapshot_date ASC, s.vendor ASC, balancing_status ASC
        """
        rows = execute_query(conn, sql, params).fetchall()

        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["snapshot_date"], row["vendor"])
            item = by_key.get(key)
            if item is None:
                item = {
                    "snapshot_date": row["snapshot_date"],
                    "vendor": row["vendor"],
                    "total": 0,
                    "nok": 0,
                    "ok": 0,
                    "other": 0,
                    "by_status": {},
                }
                by_key[key] = item
            count = int(row["sector_count"] or 0)
            status = str(row["balancing_status"] or "UNKNOWN").upper()
            item["total"] += count
            item["by_status"][status] = count
            if status == config.NOK_STATUS_VALUE:
                item["nok"] += count
            elif status == "OK":
                item["ok"] += count
            else:
                item["other"] += count

        return sorted(by_key.values(), key=lambda r: (r["snapshot_date"], r["vendor"]))
    finally:
        if own:
            conn.close()


def sector_status_trend(
    start_date: date,
    end_date: date,
    *,
    vendor: str = "nokia",
    sector_ids: list[str] | None = None,
    status_filter: str | None = None,
    limit: int = 500,
    conn=None,
) -> dict[str, Any]:
    """
    Return sector balancing status across multiple snapshot dates.

    When ``sector_ids`` is omitted, includes sectors matching ``status_filter``
    on the latest snapshot date in range (defaults to NOK).
    """
    own = conn is None
    conn = conn or connect_network_balance()
    init_schema(conn)
    start = min(start_date, end_date)
    end = max(start_date, end_date)
    vendor_key = vendor.lower()
    status_filter = (status_filter or config.NOK_STATUS_VALUE).upper()

    try:
        date_rows = execute_query(
            conn,
            """
            SELECT DISTINCT snapshot_date
            FROM balance_snapshots
            WHERE vendor = ? AND snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY snapshot_date ASC
            """,
            (vendor_key, start.isoformat(), end.isoformat()),
        ).fetchall()
        dates = [str(r["snapshot_date"]) for r in date_rows]
        if not dates:
            return {"dates": [], "sectors": [], "vendor": vendor_key}

        normalized_ids = [_normalize_sector(sid) for sid in (sector_ids or []) if str(sid or "").strip()]
        normalized_ids = [sid for sid in dict.fromkeys(normalized_ids) if sid]

        if not normalized_ids:
            latest = dates[-1]
            params: list[Any] = [vendor_key, latest]
            sql = """
                SELECT sector_id
                FROM balance_sectors bs
                JOIN balance_snapshots s ON s.id = bs.snapshot_id
                WHERE s.vendor = ? AND s.snapshot_date = ?
            """
            if status_filter and status_filter != "ALL":
                sql += " AND bs.balancing_status = ?"
                params.append(status_filter)
            sql += " ORDER BY sector_id LIMIT ?"
            params.append(int(limit))
            id_rows = execute_query(conn, sql, params).fetchall()
            normalized_ids = [str(r["sector_id"]) for r in id_rows]

        if not normalized_ids:
            return {"dates": dates, "sectors": [], "vendor": vendor_key}

        placeholders = ",".join("?" for _ in normalized_ids)
        history_rows = execute_query(
            conn,
            f"""
            SELECT s.snapshot_date, bs.sector_id, bs.balancing_status,
                   bs.highest_layer, bs.lowest_layer
            FROM balance_sectors bs
            JOIN balance_snapshots s ON s.id = bs.snapshot_id
            WHERE s.vendor = ?
              AND s.snapshot_date >= ? AND s.snapshot_date <= ?
              AND bs.sector_id IN ({placeholders})
            ORDER BY bs.sector_id ASC, s.snapshot_date ASC
            """,
            [vendor_key, start.isoformat(), end.isoformat(), *normalized_ids],
        ).fetchall()

        by_sector: dict[str, dict[str, Any]] = {}
        for row in history_rows:
            sid = str(row["sector_id"])
            item = by_sector.setdefault(sid, {
                "sector_id": sid,
                "history": {},
            })
            day = str(row["snapshot_date"])
            item["history"][day] = {
                "balancing_status": row["balancing_status"],
                "highest_layer": row["highest_layer"],
                "lowest_layer": row["lowest_layer"],
            }

        sectors = []
        for sid in normalized_ids:
            item = by_sector.get(sid, {"sector_id": sid, "history": {}})
            history_list = []
            for day in dates:
                entry = item["history"].get(day)
                history_list.append({
                    "date": day,
                    "balancing_status": entry.get("balancing_status") if entry else None,
                    "highest_layer": entry.get("highest_layer") if entry else None,
                    "lowest_layer": entry.get("lowest_layer") if entry else None,
                })
            sectors.append({
                "sector_id": sid,
                "history": history_list,
            })

        return {
            "dates": dates,
            "sectors": sectors,
            "vendor": vendor_key,
            "status_filter": status_filter,
        }
    finally:
        if own:
            conn.close()


def db_has_data(vendor: str | None = None) -> bool:
    conn = connect_network_balance()
    init_schema(conn)
    try:
        if vendor:
            row = execute_query(
                conn,
                "SELECT 1 FROM balance_snapshots WHERE vendor = ? LIMIT 1",
                (vendor.lower(),),
            ).fetchone()
        else:
            row = execute_query(conn, "SELECT 1 FROM balance_snapshots LIMIT 1").fetchone()
        return row is not None
    finally:
        conn.close()
