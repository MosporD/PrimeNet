"""
Load normalized neighbor handover rows into ``neighbor_hourly`` (legacy).

For Nokia NetAct exports under SFTP, prefer:

- ``python scripts/pull_nokia_neighbor_raw.py``
- ``python scripts/load_nokia_neighbor_raw_to_db.py``

which populate ``nokia_neighbor_2g`` / ``nokia_neighbor_3g`` / ``nokia_neighbor_4g_intra`` /
``nokia_neighbor_4g_inter`` (legacy ``nokia_neighbor_4g`` is removed on 4G load).

Usage (legacy CSV/Excel with mapped columns):

  python scripts/load_neighbor_reports.py --vendor Nokia --technology 4G-FDD --path "raw/neighbor"
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import NEIGHBOR_KPI_DB


def _ensure_legacy_neighbor_hourly_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS neighbor_hourly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL,
            technology TEXT NOT NULL,
            period_start TEXT NOT NULL,
            source_cell TEXT NOT NULL,
            source_cell_norm TEXT NOT NULL,
            target_cell TEXT NOT NULL,
            target_cell_norm TEXT NOT NULL,
            ho_attempts REAL NOT NULL,
            ho_successes REAL,
            ho_success_rate REAL,
            raw_source_cell TEXT,
            raw_target_cell TEXT,
            updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE(vendor, technology, period_start, source_cell_norm, target_cell_norm)
        );
        CREATE INDEX IF NOT EXISTS idx_neighbor_hourly_scope
            ON neighbor_hourly(technology, vendor, period_start);
        CREATE INDEX IF NOT EXISTS idx_neighbor_hourly_source_time
            ON neighbor_hourly(source_cell_norm, period_start);
        CREATE INDEX IF NOT EXISTS idx_neighbor_hourly_target_time
            ON neighbor_hourly(target_cell_norm, period_start);
        CREATE INDEX IF NOT EXISTS idx_neighbor_hourly_attempts
            ON neighbor_hourly(technology, period_start, ho_attempts);
        """
    )


def _norm(v: object) -> str:
    return str(v or "").strip()


def _norm_cell(v: object) -> str:
    return re.sub(r"\s+", " ", _norm(v)).lower()


def _to_num(v: object) -> float | None:
    if v is None:
        return None
    s = _norm(v).replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _resolve_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str | None:
    by_key = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias in by_key:
            return by_key[alias]
    if required:
        raise ValueError(f"Missing required column. Tried aliases: {aliases}")
    return None


def _parse_period(v: object) -> str | None:
    s = _norm(v)
    if not s:
        return None
    s = re.sub(r"\s+[A-Za-z]{2,5}$", "", s).strip()
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%y %H:%M",
        "%d/%m/%Y %H:%M",
        "%m.%d.%y %H:%M:%S",
        "%m.%d.%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%y %H:%M",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    p = pd.to_datetime(s, errors="coerce")
    if pd.isna(p):
        return None
    return p.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S")


def _read_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl")
    sep = ";" if ext in (".txt", ".csv") else ","
    try:
        return pd.read_csv(path, sep=sep, low_memory=False)
    except Exception:
        return pd.read_csv(path, sep=",", low_memory=False)


def _iter_input_files(root: str) -> list[str]:
    out: list[str] = []
    for cur, _, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in (".csv", ".txt", ".xlsx", ".xls"):
                out.append(os.path.join(cur, fn))
    return sorted(out)


def _neighbor_db_uses_slim_2g_export(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nokia_neighbor_2g'"
    ).fetchone()
    if not row:
        return False
    for r in conn.execute("PRAGMA table_info(nokia_neighbor_2g)"):
        if r[1] == "source_cell_id":
            return True
    return False


def load_reports(vendor: str, technology: str, input_path: str) -> tuple[int, int]:
    files = [input_path] if os.path.isfile(input_path) else _iter_input_files(input_path)
    if not files:
        raise FileNotFoundError(f"No supported files found under: {input_path}")

    conn = sqlite3.connect(NEIGHBOR_KPI_DB, timeout=30)
    try:
        if _neighbor_db_uses_slim_2g_export(conn):
            raise RuntimeError(
                "neighbor_kpis.db already uses slim nokia_neighbor_2g (SFTP pipeline). "
                "Refusing to create neighbor_hourly. Use scripts/load_nokia_neighbor_raw_to_db.py instead."
            )
        _ensure_legacy_neighbor_hourly_schema(conn)
        inserted = 0
        scanned = 0
        for path in files:
            df = _read_file(path)
            if df.empty:
                continue

            src_col = _resolve_column(df, ["source_cell", "source cell", "src_cell", "from_cell"])
            dst_col = _resolve_column(df, ["target_cell", "target cell", "tgt_cell", "to_cell"])
            ts_col = _resolve_column(df, ["period_start", "time", "timestamp", "period_start_time"])
            att_col = _resolve_column(df, ["ho_attempts", "attempts", "handover_attempts"])
            succ_col = _resolve_column(df, ["ho_successes", "successes", "handover_successes"], required=False)
            rate_col = _resolve_column(df, ["ho_success_rate", "success_rate", "handover_success_rate"], required=False)

            rows: list[tuple] = []
            for _, rec in df.iterrows():
                scanned += 1
                src_raw = _norm(rec.get(src_col))
                dst_raw = _norm(rec.get(dst_col))
                if not src_raw or not dst_raw:
                    continue
                period_start = _parse_period(rec.get(ts_col))
                attempts = _to_num(rec.get(att_col))
                if not period_start or attempts is None:
                    continue
                successes = _to_num(rec.get(succ_col)) if succ_col else None
                rate = _to_num(rec.get(rate_col)) if rate_col else None
                if rate is None and successes is not None and attempts > 0:
                    rate = (successes / attempts) * 100.0
                rows.append(
                    (
                        vendor,
                        technology,
                        period_start,
                        src_raw,
                        _norm_cell(src_raw),
                        dst_raw,
                        _norm_cell(dst_raw),
                        float(attempts),
                        successes,
                        rate,
                        src_raw,
                        dst_raw,
                    )
                )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO neighbor_hourly (
                        vendor, technology, period_start,
                        source_cell, source_cell_norm,
                        target_cell, target_cell_norm,
                        ho_attempts, ho_successes, ho_success_rate,
                        raw_source_cell, raw_target_cell
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(vendor, technology, period_start, source_cell_norm, target_cell_norm)
                    DO UPDATE SET
                        source_cell=excluded.source_cell,
                        target_cell=excluded.target_cell,
                        ho_attempts=excluded.ho_attempts,
                        ho_successes=excluded.ho_successes,
                        ho_success_rate=excluded.ho_success_rate,
                        raw_source_cell=excluded.raw_source_cell,
                        raw_target_cell=excluded.raw_target_cell,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    rows,
                )
                inserted += len(rows)
            print(f"[neighbor-load] {os.path.basename(path)} rows={len(rows)}")
        conn.commit()
        return inserted, scanned
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True, help="Vendor scope, e.g., Nokia or Huawei")
    ap.add_argument("--technology", required=True, help="Tech scope, e.g., 2G/3G/4G-FDD/4G-TDD/5G")
    ap.add_argument("--path", required=True, help="File or folder containing neighbor reports")
    args = ap.parse_args()

    inserted, scanned = load_reports(args.vendor.strip(), args.technology.strip(), args.path.strip())
    print(f"[neighbor-load] scanned={scanned} upserted={inserted} db={NEIGHBOR_KPI_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
