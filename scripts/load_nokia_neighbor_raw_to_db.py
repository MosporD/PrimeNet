"""
Load **Nokia** neighbor exports into ``neighbor_kpis.db`` only.

  python scripts/load_nokia_neighbor_raw_to_db.py              # Nokia: wide raw merge (default)
  python scripts/load_nokia_neighbor_raw_to_db.py --slim       # Slim tables for map linking

**Huawei** wide PRS lives in ``huawei_neighbor_raw.db`` — use
``python scripts/load_huawei_neighbor_wide_to_db.py`` (not this script).

**Default (wide raw):** merged CSV columns (sanitized) + ``_source_file`` / ``_ingested_at`` into
``nokia_neighbor_2g`` / ``nokia_neighbor_3g`` / ``nokia_neighbor_4g``.
No column mapping; optional ``--slim`` restores NetAct slim schemas for ``neighbor_raw_linking``.

**Nokia** with ``--slim``: drops legacy ``neighbor_hourly`` / ``neighbor_cell_index`` and loads
slim ``nokia_neighbor_*`` + 4G intra/inter (intra/inter are Nokia-specific).
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from sync_config import NEIGHBOR_KPI_DB, NOKIA_NEIGHBOR_TECH_TABLES
from pipeline.paths import raw_path

from modules.network_map.neighbor_raw_linking import (  # noqa: E402
    _pick_2g_neighbor_attempt_column,
    _pick_3g_neighbor_attempt_column,
    _pick_3g_neighbor_completion_column,
    _pick_4g_inter_attempt_column,
    _pick_4g_inter_sr_column,
    _pick_4g_neighbor_attempt_column,
    _pick_4g_neighbor_sr_column,
    _pick_ci_column,
    _pick_column,
    _pick_ho_metric_column,
)

MAX_SQLITE_COLUMNS = 1800

_TABULAR_EXT = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".xlsm")


@dataclass(frozen=True)
class NeighborVendorLoad:
    """Per-vendor paths and SQLite table names for neighbor raw ingest."""

    slug: str
    raw_root: str
    tech_tables: dict[str, str]
    intra_4g: str
    inter_4g: str
    drop_legacy_hourly: bool
    legacy_wide_4g_table: str | None
    wide_4g_table: str
    slim: bool


def _neighbor_load_cfg(vendor: str, *, slim: bool) -> NeighborVendorLoad:
    v = (vendor or "nokia").strip().lower()
    if v != "nokia":
        raise ValueError("Only Nokia is supported; use scripts/load_huawei_neighbor_wide_to_db.py for Huawei.")
    return NeighborVendorLoad(
        slug="nokia",
        raw_root=raw_path("nokia", "neighbor", "all", "hourly"),
        tech_tables=dict(NOKIA_NEIGHBOR_TECH_TABLES),
        intra_4g="nokia_neighbor_4g_intra",
        inter_4g="nokia_neighbor_4g_inter",
        drop_legacy_hourly=True,
        legacy_wide_4g_table="nokia_neighbor_4g",
        wide_4g_table="nokia_neighbor_4g",
        slim=slim,
    )


def _count_neighbor_tabular_files(raw_root: str) -> int:
    n = 0
    for tech in ("2G", "3G", "4G"):
        folder = os.path.join(raw_root, tech)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.lower().endswith(_TABULAR_EXT) and os.path.isfile(os.path.join(folder, name)):
                n += 1
    return n


def _sanitize_col(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name).strip())
    if not s:
        return "col"
    if s[0].isdigit():
        s = "c_" + s
    return s[:200]


def _read_tabular(path: str, *, use_huawei_prs: bool = False) -> pd.DataFrame:
    if use_huawei_prs:
        from modules.network_map.huawei_prs_tabular import read_huawei_prs_tabular

        return read_huawei_prs_tabular(path, log="neighbor-raw")
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, dtype=str, engine="openpyxl")
    sep = ";" if ext in (".csv", ".txt") else ","
    try:
        return pd.read_csv(path, sep=sep, dtype=str, low_memory=False, encoding="utf-8")
    except Exception:
        return pd.read_csv(path, sep=sep, dtype=str, low_memory=False, encoding="latin-1")


def _drop_nonpositive_attempt_rows(df: pd.DataFrame, attempts_col: str = "ho_attempts") -> pd.DataFrame:
    """Remove rows where attempts are missing, zero, or negative (not meaningful for HO stats)."""
    if attempts_col not in df.columns or df.empty:
        return df
    v = pd.to_numeric(df[attempts_col], errors="coerce").fillna(0.0)
    return df.loc[v > 0].reset_index(drop=True)


def _drop_legacy_neighbor(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP INDEX IF EXISTS idx_neighbor_hourly_scope;
        DROP INDEX IF EXISTS idx_neighbor_hourly_source_time;
        DROP INDEX IF EXISTS idx_neighbor_hourly_target_time;
        DROP INDEX IF EXISTS idx_neighbor_hourly_attempts;
        DROP TABLE IF EXISTS neighbor_hourly;
        DROP TABLE IF EXISTS neighbor_cell_index;
        """
    )


def _empty_2g_slim_columns() -> list[str]:
    return ["source_cell_id", "target_cell_id", "ho_attempts", "_source_file", "_ingested_at"]


def _empty_3g_slim_columns() -> list[str]:
    return [
        "scid_id",
        "tcid_id",
        "ho_attempts",
        "ho_completions",
        "_source_file",
        "_ingested_at",
    ]


def _nokia_neighbor_table_names(load: NeighborVendorLoad) -> list[str]:
    names = list(load.tech_tables.values()) + [load.intra_4g, load.inter_4g]
    if load.wide_4g_table:
        names.append(load.wide_4g_table)
    if load.legacy_wide_4g_table and load.legacy_wide_4g_table != load.wide_4g_table:
        names.append(load.legacy_wide_4g_table)
    return list(dict.fromkeys(names))


def _drop_nokia_neighbor_tables(conn: sqlite3.Connection, load: NeighborVendorLoad) -> None:
    """Remove all Nokia neighbor tables so each load is a full replace, not an append."""
    for table in _nokia_neighbor_table_names(load):
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')


def _write_empty_nokia_neighbor_tables(conn: sqlite3.Connection, load: NeighborVendorLoad) -> None:
    """Create zero-row neighbor tables after a pull with no export files."""
    if load.slim:
        pd.DataFrame(columns=_empty_2g_slim_columns()).to_sql(
            load.tech_tables["2G"], conn, if_exists="replace", index=False, chunksize=800
        )
        pd.DataFrame(columns=_empty_3g_slim_columns()).to_sql(
            load.tech_tables["3G"], conn, if_exists="replace", index=False, chunksize=800
        )
        empty_4g = pd.DataFrame(columns=_empty_4g_slim_columns())
        empty_4g.to_sql(load.intra_4g, conn, if_exists="replace", index=False, chunksize=800)
        empty_4g.to_sql(load.inter_4g, conn, if_exists="replace", index=False, chunksize=800)
        return

    for table in load.tech_tables.values():
        pd.DataFrame(columns=["_no_export_rows"]).to_sql(
            table, conn, if_exists="replace", index=False, chunksize=800
        )
    empty_4g = pd.DataFrame(columns=_empty_4g_slim_columns())
    empty_4g.to_sql(load.intra_4g, conn, if_exists="replace", index=False, chunksize=800)
    empty_4g.to_sql(load.inter_4g, conn, if_exists="replace", index=False, chunksize=800)
    pd.DataFrame(columns=["_no_export_rows"]).to_sql(
        load.wide_4g_table, conn, if_exists="replace", index=False, chunksize=800
    )


def _build_2g_slim_dataframe(merged: pd.DataFrame) -> pd.DataFrame | None:
    """Reduce wide 2G export to source_cell_id, target_cell_id, ho_attempts (+ provenance)."""
    cols = list(merged.columns)
    seg = _pick_column(cols, "source_cell_id", "Source_Cell_ID", "Segment_Name", "SegmentName", "segment_name", "Segment")
    ci = _pick_ci_column(cols) or _pick_column(
        cols, "target_cell_id", "Target_Cell_ID", "Target_CI", "target_ci"
    )
    att = _pick_2g_neighbor_attempt_column(cols)
    if not att:
        att, _ = _pick_ho_metric_column(cols)
    if not seg or not ci:
        print(f"[neighbor-raw] 2G: missing Segment/CI columns (seg={seg!r}, ci={ci!r}); skip slim build")
        return None
    ho = pd.to_numeric(merged[att], errors="coerce") if att else pd.Series(0.0, index=merged.index)
    out = pd.DataFrame(
        {
            "source_cell_id": merged[seg].astype(str).str.strip(),
            "target_cell_id": merged[ci].astype(str).str.strip(),
            "ho_attempts": ho.fillna(0.0),
            "_source_file": merged["_source_file"],
            "_ingested_at": merged["_ingested_at"],
        }
    )
    bad = {"", "nan", "none", "null"}
    m = ~out["source_cell_id"].str.lower().isin(bad) & ~out["target_cell_id"].str.lower().isin(bad)
    out = out.loc[m].reset_index(drop=True)
    return _drop_nonpositive_attempt_rows(out, "ho_attempts")


def _build_3g_slim_dataframe(merged: pd.DataFrame) -> pd.DataFrame | None:
    """Reduce wide 3G export to scid_id, tcid_id, ho_attempts, ho_completions (+ provenance)."""
    cols = list(merged.columns)
    sc = _pick_column(
        cols,
        "scid_id",
        "SCID_ID",
        "Scid_ID",
        "scell_id",
        "SCell_ID",
        "scid",
        "SCID",
        "source_ci",
        "Source_CI",
        "s_c_id",
    )
    tc = _pick_column(
        cols,
        "tcid_id",
        "TCID_ID",
        "Tcid_ID",
        "target_cell_id",
        "Target_Cell_ID",
    ) or _pick_ci_column(cols)
    att = _pick_3g_neighbor_attempt_column(cols)
    if not att:
        att, _ = _pick_ho_metric_column(cols)
    compl = _pick_3g_neighbor_completion_column(cols)
    if not sc or not tc:
        print(f"[neighbor-raw] 3G: missing scid/tcid columns (sc={sc!r}, tc={tc!r}); skip slim build")
        return None
    if not att:
        print(f"[neighbor-raw] 3G: missing attempts column (M1013C0 / SHO_ADJ…ATT); skip slim build")
        return None
    if not compl:
        print("[neighbor-raw] 3G: missing completions column (M1013C1); ho_completions set to 0")
    ho_a = pd.to_numeric(merged[att], errors="coerce")
    ho_c = pd.to_numeric(merged[compl], errors="coerce") if compl else pd.Series(0.0, index=merged.index)
    out = pd.DataFrame(
        {
            "scid_id": merged[sc].astype(str).str.strip(),
            "tcid_id": merged[tc].astype(str).str.strip(),
            "ho_attempts": ho_a.fillna(0.0),
            "ho_completions": ho_c.fillna(0.0),
            "_source_file": merged["_source_file"],
            "_ingested_at": merged["_ingested_at"],
        }
    )
    bad = {"", "nan", "none", "null"}
    m = ~out["scid_id"].str.lower().isin(bad) & ~out["tcid_id"].str.lower().isin(bad)
    out = out.loc[m].reset_index(drop=True)
    return _drop_nonpositive_attempt_rows(out, "ho_attempts")


def _build_4g_intra_slim_dataframe(merged: pd.DataFrame) -> pd.DataFrame | None:
    """Reduce wide 4G export to intra-eNB metrics: source_lncel_name, eci_id, ho_attempts, ho_success_rate."""
    cols = list(merged.columns)
    src = _pick_column(
        cols,
        "source_lncel_name",
        "Source_LNCEL_name",
        "SourceLNCELname",
        "Source_LNCEL_Name",
        "SourceLNCELName",
    )
    eci = _pick_column(
        cols,
        "eci_id",
        "ECI_ID",
        "Eci_ID",
        "ECI",
        "Eci",
        "eci",
        "Target_ECI",
        "target_eci",
    )
    att = _pick_4g_neighbor_attempt_column(cols)
    if not att:
        att, _ = _pick_ho_metric_column(cols)
    sr = _pick_4g_neighbor_sr_column(cols)
    if not src or not eci:
        print(f"[neighbor-raw] 4G: missing LNCEL/ECI columns (src={src!r}, eci={eci!r}); skip slim build")
        return None
    if not att:
        print("[neighbor-raw] 4G: missing intra-eNB neighbor attempts column; skip slim build")
        return None
    if not sr:
        print("[neighbor-raw] 4G: missing Adj Intra eNB HO SR column; skip slim build")
        return None
    ho_a = pd.to_numeric(merged[att], errors="coerce")
    ho_sr = pd.to_numeric(merged[sr], errors="coerce")
    out = pd.DataFrame(
        {
            "source_lncel_name": merged[src].astype(str).str.strip(),
            "eci_id": merged[eci].astype(str).str.strip(),
            "ho_attempts": ho_a.fillna(0.0),
            "ho_success_rate": ho_sr,
            "_source_file": merged["_source_file"],
            "_ingested_at": merged["_ingested_at"],
        }
    )
    bad = {"", "nan", "none", "null"}
    m = ~out["source_lncel_name"].str.lower().isin(bad) & ~out["eci_id"].str.lower().isin(bad)
    out = out.loc[m].reset_index(drop=True)
    out = out.loc[pd.to_numeric(out["ho_success_rate"], errors="coerce").notna()].reset_index(drop=True)
    return _drop_nonpositive_attempt_rows(out, "ho_attempts")


def _build_4g_inter_slim_dataframe(merged: pd.DataFrame) -> pd.DataFrame | None:
    """Inter-eNB neighbor attempts + Adj Inter eNB HO SR (same slim column names as intra)."""
    cols = list(merged.columns)
    src = _pick_column(
        cols,
        "source_lncel_name",
        "Source_LNCEL_name",
        "SourceLNCELname",
        "Source_LNCEL_Name",
        "SourceLNCELName",
    )
    eci = _pick_column(
        cols,
        "eci_id",
        "ECI_ID",
        "Eci_ID",
        "ECI",
        "Eci",
        "eci",
        "Target_ECI",
        "target_eci",
    )
    att = _pick_4g_inter_attempt_column(cols)
    sr = _pick_4g_inter_sr_column(cols)
    if not src or not eci:
        print(f"[neighbor-raw] 4G inter: missing LNCEL/ECI columns (src={src!r}, eci={eci!r}); skip slim build")
        return None
    if not att:
        print("[neighbor-raw] 4G inter: missing inter-eNB neighbor attempts column; skip slim build")
        return None
    if not sr:
        print("[neighbor-raw] 4G inter: missing Adj Inter eNB HO SR column; skip slim build")
        return None
    ho_a = pd.to_numeric(merged[att], errors="coerce")
    ho_sr = pd.to_numeric(merged[sr], errors="coerce")
    out = pd.DataFrame(
        {
            "source_lncel_name": merged[src].astype(str).str.strip(),
            "eci_id": merged[eci].astype(str).str.strip(),
            "ho_attempts": ho_a.fillna(0.0),
            "ho_success_rate": ho_sr,
            "_source_file": merged["_source_file"],
            "_ingested_at": merged["_ingested_at"],
        }
    )
    bad = {"", "nan", "none", "null"}
    m = ~out["source_lncel_name"].str.lower().isin(bad) & ~out["eci_id"].str.lower().isin(bad)
    out = out.loc[m].reset_index(drop=True)
    out = out.loc[pd.to_numeric(out["ho_success_rate"], errors="coerce").notna()].reset_index(drop=True)
    return _drop_nonpositive_attempt_rows(out, "ho_attempts")


def _empty_4g_slim_columns() -> list[str]:
    return ["source_lncel_name", "eci_id", "ho_attempts", "ho_success_rate", "_source_file", "_ingested_at"]


def _write_merged_wide_only(conn: sqlite3.Connection, merged: pd.DataFrame, table: str, tech: str) -> int:
    """Persist full merged export (sanitized headers) with no slim mapping or HO filters."""
    if merged.shape[1] > MAX_SQLITE_COLUMNS:
        keep = list(merged.columns[:MAX_SQLITE_COLUMNS])
        merged = merged[keep]
        print(f"[neighbor-raw] {tech}: truncated to {MAX_SQLITE_COLUMNS} columns")
    merged.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
    n = len(merged)
    print(f"[neighbor-raw] {tech} -> {table}: {n} rows, {merged.shape[1]} columns (wide raw)")
    return n


def _load_4g_neighbor_tables(conn: sqlite3.Connection, load: NeighborVendorLoad) -> int:
    """Load raw/<vendor>/neighbor/4G — wide raw table and empty intra/inter, or slim intra+inter."""
    tech = "4G"
    intra_table = load.intra_4g
    inter_table = load.inter_4g
    folder = os.path.join(load.raw_root, tech)
    if load.slim and load.legacy_wide_4g_table:
        conn.execute(f'DROP TABLE IF EXISTS "{load.legacy_wide_4g_table}"')
    if not os.path.isdir(folder):
        print(f"[neighbor-raw] skip 4G: missing folder {folder}")
        empty = pd.DataFrame(columns=_empty_4g_slim_columns())
        empty.to_sql(intra_table, conn, if_exists="replace", index=False, chunksize=800)
        empty.to_sql(inter_table, conn, if_exists="replace", index=False, chunksize=800)
        return 0

    tabular_names = [
        name
        for name in sorted(os.listdir(folder))
        if os.path.isfile(os.path.join(folder, name)) and name.lower().endswith(_TABULAR_EXT)
    ]

    frames: list[pd.DataFrame] = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        low = name.lower()
        if not low.endswith(_TABULAR_EXT):
            continue
        try:
            df = _read_tabular(path, use_huawei_prs=(load.slug == "huawei"))
        except Exception as ex:
            print(f"[neighbor-raw] skip {name}: {ex}")
            continue
        if df is None:
            continue
        if df.empty and load.slim:
            continue
        df = df.copy()
        df.columns = [_sanitize_col(c) for c in df.columns]
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        df.insert(0, "_source_file", name)
        df.insert(1, "_ingested_at", stamp)
        frames.append(df)

    if not frames:
        if tabular_names:
            print(
                f"[neighbor-raw] 4G: {len(tabular_names)} export(s) present but no data rows "
                f"({', '.join(tabular_names)})"
            )
        else:
            print(f"[neighbor-raw] 4G: no tabular files in {folder}")
        empty = pd.DataFrame(columns=_empty_4g_slim_columns())
        empty.to_sql(intra_table, conn, if_exists="replace", index=False, chunksize=800)
        empty.to_sql(inter_table, conn, if_exists="replace", index=False, chunksize=800)
        if not load.slim:
            pd.DataFrame(columns=["_no_export_rows"]).to_sql(
                load.wide_4g_table, conn, if_exists="replace", index=False, chunksize=800
            )
            print(f"[neighbor-raw] 4G -> {load.wide_4g_table}: 0 rows (wide raw)")
        return 0

    merged = pd.concat(frames, ignore_index=True, sort=False)

    if not load.slim:
        n_wide = _write_merged_wide_only(conn, merged, load.wide_4g_table, tech)
        empty = pd.DataFrame(columns=_empty_4g_slim_columns())
        empty.to_sql(intra_table, conn, if_exists="replace", index=False, chunksize=800)
        empty.to_sql(inter_table, conn, if_exists="replace", index=False, chunksize=800)
        print(f"[neighbor-raw] 4G -> {intra_table}, {inter_table}: 0 rows (wide-raw mode; use {load.wide_4g_table})")
        return n_wide

    total = 0
    intra = _build_4g_intra_slim_dataframe(merged)
    if intra is not None and not intra.empty:
        intra.to_sql(intra_table, conn, if_exists="replace", index=False, chunksize=800)
        n = len(intra)
        total += n
        print(
            f"[neighbor-raw] 4G -> {intra_table}: {n} rows "
            "(slim: source_lncel_name, eci_id, ho_attempts, ho_success_rate intra SR)"
        )
    else:
        pd.DataFrame(columns=_empty_4g_slim_columns()).to_sql(
            intra_table, conn, if_exists="replace", index=False, chunksize=800
        )
        print(f"[neighbor-raw] 4G -> {intra_table}: 0 rows (slim schema; no mappable intra rows)")

    inter = _build_4g_inter_slim_dataframe(merged)
    if inter is not None and not inter.empty:
        inter.to_sql(inter_table, conn, if_exists="replace", index=False, chunksize=800)
        n = len(inter)
        total += n
        print(
            f"[neighbor-raw] 4G -> {inter_table}: {n} rows "
            "(slim: source_lncel_name, eci_id, ho_attempts, ho_success_rate inter SR)"
        )
    else:
        pd.DataFrame(columns=_empty_4g_slim_columns()).to_sql(
            inter_table, conn, if_exists="replace", index=False, chunksize=800
        )
        print(f"[neighbor-raw] 4G -> {inter_table}: 0 rows (slim schema; no mappable inter rows)")

    return total


def _load_tech(conn: sqlite3.Connection, tech: str, table: str, load: NeighborVendorLoad) -> int:
    folder = os.path.join(load.raw_root, tech)
    if not os.path.isdir(folder):
        print(f"[neighbor-raw] skip {tech}: missing folder {folder}")
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        return 0

    tabular_names = [
        name
        for name in sorted(os.listdir(folder))
        if os.path.isfile(os.path.join(folder, name)) and name.lower().endswith(_TABULAR_EXT)
    ]

    frames: list[pd.DataFrame] = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        low = name.lower()
        if not low.endswith(_TABULAR_EXT):
            continue
        try:
            df = _read_tabular(path, use_huawei_prs=(load.slug == "huawei"))
        except Exception as ex:
            print(f"[neighbor-raw] skip {name}: {ex}")
            continue
        if df is None:
            continue
        if df.empty and load.slim:
            continue
        df = df.copy()
        df.columns = [_sanitize_col(c) for c in df.columns]
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        df.insert(0, "_source_file", name)
        df.insert(1, "_ingested_at", stamp)
        frames.append(df)

    if not frames:
        if not tabular_names:
            print(f"[neighbor-raw] {tech}: no tabular files in {folder}")
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            return 0
        print(
            f"[neighbor-raw] {tech}: {len(tabular_names)} export(s) present but no data rows "
            f"({', '.join(tabular_names)})"
        )
        if load.slim:
            if tech == "2G" and table.endswith("_neighbor_2g"):
                pd.DataFrame(
                    columns=["source_cell_id", "target_cell_id", "ho_attempts", "_source_file", "_ingested_at"]
                ).to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
            elif tech == "3G" and table.endswith("_neighbor_3g"):
                pd.DataFrame(
                    columns=[
                        "scid_id",
                        "tcid_id",
                        "ho_attempts",
                        "ho_completions",
                        "_source_file",
                        "_ingested_at",
                    ]
                ).to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
            else:
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        else:
            pd.DataFrame(columns=["_no_export_rows"]).to_sql(
                table, conn, if_exists="replace", index=False, chunksize=800
            )
            print(f"[neighbor-raw] {tech} -> {table}: 0 rows (wide raw)")
        return 0

    merged = pd.concat(frames, ignore_index=True, sort=False)
    if not load.slim:
        return _write_merged_wide_only(conn, merged, table, tech)

    if tech == "2G" and table.endswith("_neighbor_2g"):
        slim = _build_2g_slim_dataframe(merged)
        if slim is not None and not slim.empty:
            slim.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
            n = len(slim)
            print(f"[neighbor-raw] {tech} -> {table}: {n} rows (slim: source_cell_id, target_cell_id, ho_attempts)")
            return n
        empty = pd.DataFrame(
            columns=["source_cell_id", "target_cell_id", "ho_attempts", "_source_file", "_ingested_at"]
        )
        empty.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
        print(f"[neighbor-raw] {tech} -> {table}: 0 rows (slim schema; wide merge had no mappable rows)")
        return 0

    if tech == "3G" and table.endswith("_neighbor_3g"):
        slim = _build_3g_slim_dataframe(merged)
        if slim is not None and not slim.empty:
            slim.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
            n = len(slim)
            print(
                f"[neighbor-raw] {tech} -> {table}: {n} rows "
                "(slim: scid_id, tcid_id, ho_attempts, ho_completions)"
            )
            return n
        empty = pd.DataFrame(
            columns=[
                "scid_id",
                "tcid_id",
                "ho_attempts",
                "ho_completions",
                "_source_file",
                "_ingested_at",
            ]
        )
        empty.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
        print(f"[neighbor-raw] {tech} -> {table}: 0 rows (slim schema; wide merge had no mappable rows)")
        return 0

    if merged.shape[1] > MAX_SQLITE_COLUMNS:
        keep = list(merged.columns[:MAX_SQLITE_COLUMNS])
        merged = merged[keep]
        print(f"[neighbor-raw] {tech}: truncated to {MAX_SQLITE_COLUMNS} columns")

    cols_wide = list(merged.columns)
    att_wide, _ = _pick_ho_metric_column(cols_wide)
    if att_wide:
        ho = pd.to_numeric(merged[att_wide], errors="coerce")
        merged = merged.loc[ho.fillna(0.0) > 0].reset_index(drop=True)

    merged.to_sql(table, conn, if_exists="replace", index=False, chunksize=800)
    n = len(merged)
    print(f"[neighbor-raw] {tech} -> {table}: {n} rows, {merged.shape[1]} columns")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Load neighbor KPI raw exports into neighbor_kpis.db")
    ap.add_argument(
        "--vendor",
        choices=("nokia",),
        default="nokia",
        help="Nokia only (Huawei → load_huawei_neighbor_wide_to_db.py → huawei_neighbor_raw.db)",
    )
    ap.add_argument(
        "--slim",
        action="store_true",
        help="Map wide exports to slim tables for neighbor_raw_linking (default: full wide merge only)",
    )
    args = ap.parse_args()
    load = _neighbor_load_cfg(args.vendor, slim=args.slim)

    n_files = _count_neighbor_tabular_files(load.raw_root)
    os.makedirs(os.path.dirname(NEIGHBOR_KPI_DB), exist_ok=True)
    conn = sqlite3.connect(NEIGHBOR_KPI_DB, timeout=120)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS huawei_neighbor_2g;
            DROP TABLE IF EXISTS huawei_neighbor_3g;
            DROP TABLE IF EXISTS huawei_neighbor_4g;
            DROP TABLE IF EXISTS huawei_neighbor_4g_intra;
            DROP TABLE IF EXISTS huawei_neighbor_4g_inter;
            """
        )
        if load.drop_legacy_hourly:
            _drop_legacy_neighbor(conn)
        _drop_nokia_neighbor_tables(conn, load)
        if n_files == 0:
            _write_empty_nokia_neighbor_tables(conn, load)
            conn.commit()
            print(f"[neighbor-raw/{load.slug}] no tabular files under {load.raw_root}/2G|3G|4G")
            print("[neighbor-raw] replaced all Nokia neighbor tables with empty schemas (full refresh)")
            if load.drop_legacy_hourly:
                print("[neighbor-raw] Pull exports: python scripts/pipeline/pull_nokia_neighbor_raw.py")
            return 0
        total = 0
        for tech, table in load.tech_tables.items():
            total += _load_tech(conn, tech, table, load)
        total += _load_4g_neighbor_tables(conn, load)
        conn.commit()
    finally:
        conn.close()
    print(f"[neighbor-raw/{load.slug}] done db={NEIGHBOR_KPI_DB} total_rows_loaded~{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
