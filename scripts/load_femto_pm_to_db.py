"""
Load Femto PM TGZ/XML files into a wide SQLite table.

Design:
- unique key: (unique_id, timestamp)
- dynamic KPI columns: one column per KPI technical name (<mt>)
"""

from __future__ import annotations

import os
import re
import sqlite3
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import FEMTO_RETENTION_DAYS, PROJECT_ROOT


RAW_FEMTO_DIR = Path(PROJECT_ROOT) / "raw" / "femto"
FEMTO_PM_DB = Path(PROJECT_ROOT) / "databases" / "cells" / "femto_pm_cells.db"
FEMTO_TABLE = "FEMTO_HOURLY"
FEMTO_VALUES_TABLE = "FEMTO_HOURLY_VALUES"
_FIXED_COLS = {
    "id", "unique_id", "timestamp", "hnb_id", "fsn", "bsr_name", "op_mode",
    "vendor", "system_type", "gp_seconds", "cbt", "mts", "archive_path", "updated_at",
}
_MAX_WIDE_TABLE_COLUMNS = 1900


def _norm_ts(raw: str) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y%m%d%H%M%S%z", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _coerce_value(v: str):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return s


def _safe_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _parse_neun_kv(neun: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(neun or "").split(","):
        p = part.strip()
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _extract_xml_from_tgz(tgz_path: Path) -> str:
    with tarfile.open(tgz_path, "r:gz") as tf:
        member = next((m for m in tf.getmembers() if m.isfile()), None)
        if member is None:
            return ""
        fh = tf.extractfile(member)
        if fh is None:
            return ""
        return fh.read().decode("utf-8", "replace")


def _parse_archive(tgz_path: Path) -> dict | None:
    xml_text = _extract_xml_from_tgz(tgz_path)
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    def t(tag: str) -> str:
        node = root.find(f".//{tag}")
        return (node.text or "").strip() if node is not None and node.text is not None else ""

    mts_raw = t("mts")
    cbt_raw = t("cbt")
    timestamp = _norm_ts(mts_raw) or _norm_ts(cbt_raw)
    if not timestamp:
        return None

    neun = t("neun")
    neun_kv = _parse_neun_kv(neun)
    unique_id = (
        neun_kv.get("HNBId")
        or neun_kv.get("Fsn")
        or ""
    ).strip()
    if not unique_id:
        return None

    row = {
        "unique_id": unique_id,
        "timestamp": timestamp,
        "hnb_id": neun_kv.get("HNBId", ""),
        "fsn": neun_kv.get("Fsn", ""),
        "bsr_name": neun_kv.get("bSRName", ""),
        "op_mode": neun_kv.get("OpMode", ""),
        "vendor": t("vn"),
        "system_type": t("st"),
        "gp_seconds": t("gp"),
        "cbt": _norm_ts(cbt_raw) or "",
        "mts": _norm_ts(mts_raw) or "",
        "archive_path": str(tgz_path.relative_to(RAW_FEMTO_DIR)).replace("\\", "/"),
    }

    # KPI extraction supports two XML patterns:
    # 1) <mt>kpi</mt><mv>value</mv> (mv under mt)
    # 2) <mi><mt>k1</mt>...<mt>kN</mt><mv><r>v1</r>...<r>vN</r></mv></mi>
    for mi in root.findall(".//mi"):
        mt_nodes = mi.findall("mt")
        if not mt_nodes:
            continue
        mt_names = [(mt.text or "").strip() for mt in mt_nodes]
        mt_names = [n for n in mt_names if n]
        if not mt_names:
            continue

        # Pattern 1: value nested directly under each mt.
        has_mt_mv = False
        for mt in mt_nodes:
            mt_name = (mt.text or "").strip()
            if not mt_name:
                continue
            mv_node = mt.find("mv")
            if mv_node is None:
                continue
            has_mt_mv = True
            if mt_name not in row:
                row[mt_name] = _coerce_value(mv_node.text or "")
        if has_mt_mv:
            continue

        # Pattern 2: values provided as <r> list in one or more mv blocks.
        for mv_node in mi.findall("mv"):
            r_nodes = mv_node.findall("r")
            if not r_nodes:
                continue
            values = [_coerce_value((r.text or "").strip()) for r in r_nodes]

            # Most common format: one value per KPI in matching order.
            if len(values) == len(mt_names):
                for kpi_name, value in zip(mt_names, values):
                    if kpi_name not in row:
                        row[kpi_name] = value
                continue

            # Fallback for odd blocks: keep single-value mapping where possible.
            if len(values) == 1 and len(mt_names) == 1 and mt_names[0] not in row:
                row[mt_names[0]] = values[0]

    return row


def _ensure_base_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_safe_ident(FEMTO_TABLE)} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            hnb_id TEXT,
            fsn TEXT,
            bsr_name TEXT,
            op_mode TEXT,
            vendor TEXT,
            system_type TEXT,
            gp_seconds TEXT,
            cbt TEXT,
            mts TEXT,
            archive_path TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(unique_id, timestamp)
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_femto_uid_ts ON {_safe_ident(FEMTO_TABLE)} (unique_id, timestamp)"
    )


def _ensure_values_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_safe_ident(FEMTO_VALUES_TABLE)} (
            unique_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            kpi_name TEXT NOT NULL,
            kpi_value REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (unique_id, timestamp, kpi_name)
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_femto_values_uid_ts ON {_safe_ident(FEMTO_VALUES_TABLE)} (unique_id, timestamp)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_femto_values_kpi ON {_safe_ident(FEMTO_VALUES_TABLE)} (kpi_name)"
    )


def _ensure_columns(conn: sqlite3.Connection, cols: list[str]) -> set[str]:
    existing = {
        r[1]
        for r in conn.execute(f"PRAGMA table_info({_safe_ident(FEMTO_TABLE)})").fetchall()
    }
    existing_count = len(existing)
    for col in cols:
        if col in existing:
            continue
        if existing_count >= _MAX_WIDE_TABLE_COLUMNS:
            # Wide table kept for quick preview only; full KPI set is stored in values table.
            break
        # Store as REAL where possible; SQLite remains flexible if text appears later.
        conn.execute(f"ALTER TABLE {_safe_ident(FEMTO_TABLE)} ADD COLUMN {_safe_ident(col)} REAL")
        existing.add(col)
        existing_count += 1
    return existing


def _upsert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    all_cols = []
    seen = set()
    for r in rows:
        for c in r.keys():
            if c in seen:
                continue
            seen.add(c)
            all_cols.append(c)

    available = _ensure_columns(conn, [c for c in all_cols if c not in ("id", "updated_at")])
    all_cols = [c for c in all_cols if c in available]

    col_sql = ", ".join(_safe_ident(c) for c in all_cols)
    val_sql = ", ".join(["?"] * len(all_cols))
    update_cols = [c for c in all_cols if c not in ("unique_id", "timestamp")]
    upd_sql = ", ".join(f"{_safe_ident(c)}=excluded.{_safe_ident(c)}" for c in update_cols)
    sql = (
        f"INSERT INTO {_safe_ident(FEMTO_TABLE)} ({col_sql}) VALUES ({val_sql}) "
        f"ON CONFLICT(unique_id, timestamp) DO UPDATE SET {upd_sql}, updated_at=CURRENT_TIMESTAMP"
    )

    batch = []
    for r in rows:
        batch.append(tuple(r.get(c) for c in all_cols))
    conn.executemany(sql, batch)
    return len(batch)


def _apply_femto_retention(conn: sqlite3.Connection, days: int) -> None:
    """Drop Femto rows older than ``days`` from values table then wide table."""
    if days <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"DELETE FROM {_safe_ident(FEMTO_VALUES_TABLE)} WHERE {_safe_ident('timestamp')} < ?",
        (cutoff,),
    )
    conn.execute(
        f"DELETE FROM {_safe_ident(FEMTO_TABLE)} WHERE {_safe_ident('timestamp')} < ?",
        (cutoff,),
    )
    print(f"[retention] femto: deleted rows with timestamp < {cutoff} (FEMTO_RETENTION_DAYS={days})")


def _upsert_values(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    items: list[tuple] = []
    for row in rows:
        unique_id = row.get("unique_id")
        timestamp = row.get("timestamp")
        if not unique_id or not timestamp:
            continue
        for k, v in row.items():
            if k in _FIXED_COLS:
                continue
            items.append((unique_id, timestamp, k, v))
    if not items:
        return 0
    conn.executemany(
        f"""
        INSERT INTO {_safe_ident(FEMTO_VALUES_TABLE)} (unique_id, timestamp, kpi_name, kpi_value, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(unique_id, timestamp, kpi_name) DO UPDATE SET
            kpi_value=excluded.kpi_value,
            updated_at=CURRENT_TIMESTAMP
        """,
        items,
    )
    return len(items)


def main() -> int:
    if not RAW_FEMTO_DIR.exists():
        print(f"[error] missing raw folder: {RAW_FEMTO_DIR}")
        return 1
    archives = sorted(RAW_FEMTO_DIR.rglob("*.tgz"))
    if not archives:
        print(f"[warn] no tgz files in {RAW_FEMTO_DIR}")
        return 0

    FEMTO_PM_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(FEMTO_PM_DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_base_table(conn)
    _ensure_values_table(conn)

    parsed_rows: list[dict] = []
    bad = 0
    for tgz in archives:
        row = _parse_archive(tgz)
        if row is None:
            bad += 1
            continue
        parsed_rows.append(row)

    upserted = _upsert_rows(conn, parsed_rows)
    value_upserts = _upsert_values(conn, parsed_rows)
    if FEMTO_RETENTION_DAYS > 0:
        _apply_femto_retention(conn, FEMTO_RETENTION_DAYS)
    conn.commit()
    total = conn.execute(f"SELECT COUNT(*) FROM {_safe_ident(FEMTO_TABLE)}").fetchone()[0]
    total_values = conn.execute(f"SELECT COUNT(*) FROM {_safe_ident(FEMTO_VALUES_TABLE)}").fetchone()[0]
    conn.close()

    print(f"[done] archives={len(archives)} parsed={len(parsed_rows)} failed={bad} upserted={upserted}")
    print(f"[done] values_upserted={value_upserts} values_rows={total_values}")
    print(f"[done] table={FEMTO_TABLE} rows={total} db={FEMTO_PM_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

