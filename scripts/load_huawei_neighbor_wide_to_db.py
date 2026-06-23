"""
Load Huawei neighbor PRS exports (wide) into HUAWEI_NEIGHBOR_RAW_DB.

Use this to inspect real Huawei column headers and counters before mapping them
in the slim neighbor loader.

  python scripts/pipeline/pull_huawei_neighbor_raw.py   # SFTP + unzip
  python scripts/load_huawei_neighbor_wide_to_db.py

PRS files often have title rows above the grid; rows before the line whose
column A is ``Date`` are dropped, then that line becomes the header.

Output (SQLite):
  - huawei_neighbor_header_catalog: tech, sql_column, original_header, position, source_files
  - huawei_neighbor_export_2g / _3g / _4g: merged wide rows + _source_file, _ingested_at
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)
from sync_config import HUAWEI_NEIGHBOR_RAW_DB, PROJECT_ROOT  # noqa: E402
from pipeline.paths import raw_path  # noqa: E402
from modules.network_map.huawei_prs_tabular import read_huawei_prs_tabular  # noqa: E402

_RAW_NEIGHBOR = raw_path("huawei", "neighbor", "all", "hourly")
_TABULAR_EXT = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")
_MAX_COLS = 1800


def _empty_export_frame() -> pd.DataFrame:
    """Zero-row frame so SQLite gets a valid CREATE TABLE (empty DataFrame has no columns)."""
    return pd.DataFrame(columns=["_no_export_rows"])


def _sanitize_col(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name).strip())
    if not s:
        return "col"
    if s[0].isdigit():
        s = "c_" + s
    return s[:200]


def _unique_sql_columns(originals: list[str]) -> list[str]:
    used: set[str] = set()
    out: list[str] = []
    for o in originals:
        base = _sanitize_col(o)
        name = base
        n = 1
        while name in used:
            n += 1
            name = f"{base}_{n}"
        used.add(name)
        out.append(name)
    return out


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS huawei_neighbor_header_catalog;
        CREATE TABLE huawei_neighbor_header_catalog (
            tech TEXT NOT NULL,
            sql_column TEXT NOT NULL,
            original_header TEXT,
            position INTEGER,
            source_files TEXT,
            PRIMARY KEY (tech, sql_column)
        );
        DROP TABLE IF EXISTS huawei_neighbor_export_2g;
        DROP TABLE IF EXISTS huawei_neighbor_export_3g;
        DROP TABLE IF EXISTS huawei_neighbor_export_4g;
        DROP TABLE IF EXISTS huawei_neighbor_wide_manifest;
        CREATE TABLE huawei_neighbor_wide_manifest (
            tech TEXT PRIMARY KEY,
            ingested_at TEXT,
            row_count INTEGER,
            col_count INTEGER,
            source_files_json TEXT
        );
        """
    )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _merge_tech(
    tech: str,
    folder: str,
    table_name: str,
    conn: sqlite3.Connection,
    catalog_accum: dict[tuple[str, str], dict],
) -> int:
    if not os.path.isdir(folder):
        _empty_export_frame().to_sql(table_name, conn, if_exists="replace", index=False, chunksize=500)
        conn.execute(
            "INSERT OR REPLACE INTO huawei_neighbor_wide_manifest (tech, ingested_at, row_count, col_count, source_files_json) VALUES (?,?,?,?,?)",
            (tech, _utc_stamp(), 0, 0, "[]"),
        )
        print(f"[huawei-neighbor-wide] {tech}: missing folder {folder}")
        return 0

    frames: list[pd.DataFrame] = []
    used_files: list[str] = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not name.lower().endswith(_TABULAR_EXT):
            continue
        try:
            df = read_huawei_prs_tabular(path, log="huawei-neighbor-wide")
        except Exception as ex:
            print(f"[huawei-neighbor-wide] skip {tech}/{name}: {ex}")
            continue
        if df is None or df.empty:
            continue
        originals = [str(c) for c in df.columns]
        sql_cols = _unique_sql_columns(originals)
        df = df.copy()
        df.columns = sql_cols
        stamp = _utc_stamp()
        df.insert(0, "_source_file", name)
        df.insert(1, "_ingested_at", stamp)
        for pos, (orig, sql) in enumerate(zip(originals, sql_cols)):
            key = (tech, sql)
            if key not in catalog_accum:
                catalog_accum[key] = {
                    "tech": tech,
                    "sql_column": sql,
                    "original_header": orig,
                    "position": pos,
                    "files": {name},
                }
            else:
                catalog_accum[key]["files"].add(name)
        frames.append(df)
        used_files.append(name)

    if not frames:
        conn.execute(
            "INSERT OR REPLACE INTO huawei_neighbor_wide_manifest (tech, ingested_at, row_count, col_count, source_files_json) VALUES (?,?,?,?,?)",
            (tech, _utc_stamp(), 0, 0, "[]"),
        )
        _empty_export_frame().to_sql(table_name, conn, if_exists="replace", index=False, chunksize=500)
        print(f"[huawei-neighbor-wide] {tech}: no tabular files in {folder}")
        return 0

    merged = pd.concat(frames, ignore_index=True, sort=False)
    if merged.shape[1] > _MAX_COLS:
        keep = list(merged.columns[:_MAX_COLS])
        merged = merged[keep]
        print(f"[huawei-neighbor-wide] {tech}: truncated to {_MAX_COLS} columns")

    merged.to_sql(table_name, conn, if_exists="replace", index=False, chunksize=800)
    n = len(merged)
    conn.execute(
        "INSERT OR REPLACE INTO huawei_neighbor_wide_manifest (tech, ingested_at, row_count, col_count, source_files_json) VALUES (?,?,?,?,?)",
        (
            tech,
            _utc_stamp(),
            n,
            merged.shape[1],
            json.dumps(used_files),
        ),
    )
    print(f"[huawei-neighbor-wide] {tech} -> {table_name}: {n} rows, {merged.shape[1]} cols, files={used_files}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Load wide Huawei neighbor exports into huawei_neighbor_raw.db")
    ap.add_argument(
        "--raw-root",
        default=_RAW_NEIGHBOR,
        help="Folder containing 2G/3G/4G subfolders (default: raw/huawei/neighbor)",
    )
    args = ap.parse_args()
    raw_root = os.path.abspath(args.raw_root)

    os.makedirs(os.path.dirname(HUAWEI_NEIGHBOR_RAW_DB), exist_ok=True)
    conn = sqlite3.connect(HUAWEI_NEIGHBOR_RAW_DB, timeout=120)
    catalog_accum: dict[tuple[str, str], dict] = {}
    try:
        _init_db(conn)
        total = 0
        for tech, table in (
            ("2G", "huawei_neighbor_export_2g"),
            ("3G", "huawei_neighbor_export_3g"),
            ("4G", "huawei_neighbor_export_4g"),
        ):
            folder = os.path.join(raw_root, tech)
            total += _merge_tech(tech, folder, table, conn, catalog_accum)

        rows_cat = []
        for _k, rec in sorted(catalog_accum.items(), key=lambda x: (x[0][0], x[0][1])):
            files = sorted(rec["files"])
            rows_cat.append(
                (
                    rec["tech"],
                    rec["sql_column"],
                    rec["original_header"],
                    int(rec["position"]),
                    ",".join(files),
                )
            )
        if rows_cat:
            conn.executemany(
                "INSERT INTO huawei_neighbor_header_catalog (tech, sql_column, original_header, position, source_files) VALUES (?,?,?,?,?)",
                rows_cat,
            )
        conn.commit()
    finally:
        conn.close()

    print(f"[huawei-neighbor-wide] done db={HUAWEI_NEIGHBOR_RAW_DB} total_rows~{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
