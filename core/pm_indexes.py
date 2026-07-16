"""
PM SQLite index maintenance for fast cell/group + time lookups.

Creates composite indexes on vendor-native columns (e.g. ``WCEL name`` + ``PERIOD_START_TIME``)
and on normalized ``cell_name`` / ``timestamp`` when present. Safe to run after every load.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Iterable

_TIME_ALIASES = (
    "timestamp",
    "time",
    "period_start_time",
    "period start time",
    "date",
)

_CELL_NAME_ALIASES = (
    "cell_name",
    "cell name",
    "bts name",
    "wcel name",
    "lncel name",
    "nrcel name",
    "cellname",
    "user label",
    "ne name",
)

_CELL_ID_EXACT = frozenset(
    {
        "wcel id",
        "lncel id",
        "nrcel id",
        "cell id",
        "cell ci",
        "eutran cell id",
        "nbiot cell id",
    }
)

_GROUP_ALIASES = (
    "group",
    "grp",
    "ws_name",
    "ws name",
)

def _norm_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _quote_ident(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def _index_suffix(table: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(table))[:40]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()]
    except sqlite3.OperationalError:
        return []


def _pick_from_aliases(cols: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    low_map = {_norm_col(c): c for c in cols}
    for alias in aliases:
        hit = low_map.get(alias)
        if hit:
            return hit
    return None


def _pick_cell_id_col(cols: list[str], cell_name_col: str | None) -> str | None:
    for col in cols:
        low = _norm_col(col)
        if low in _CELL_ID_EXACT:
            return col
    for col in cols:
        low = _norm_col(col)
        if col == cell_name_col:
            continue
        if not low.endswith(" id"):
            continue
        if any(x in low for x in ("mrbts", "lnbts", "nrbts", "gbsc", "rnc", "plmn", "bcf")):
            continue
        if any(x in low for x in ("wcel", "lncel", "nrcel", "cell", "bts", "ci")):
            return col
    return None


def _create_composite_index(
    conn: sqlite3.Connection,
    table: str,
    index_name: str,
    col_a: str,
    col_b: str,
) -> bool:
    try:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {_quote_ident(index_name)} "
            f"ON {_quote_ident(table)} ({_quote_ident(col_a)}, {_quote_ident(col_b)})"
        )
        return True
    except sqlite3.OperationalError:
        return False


def _create_single_index(
    conn: sqlite3.Connection,
    table: str,
    index_name: str,
    col: str,
) -> bool:
    try:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {_quote_ident(index_name)} "
            f"ON {_quote_ident(table)} ({_quote_ident(col)})"
        )
        return True
    except sqlite3.OperationalError:
        return False


def _all_alias_cols(cols: list[str], aliases: tuple[str, ...]) -> list[str]:
    """Return every physical column matching aliases (not just the first)."""
    low_map = {_norm_col(c): c for c in cols}
    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        hit = low_map.get(alias)
        if hit and hit not in seen:
            seen.add(hit)
            out.append(hit)
    return out


def ensure_table_indexes(conn: sqlite3.Connection, table: str) -> list[str]:
    """
    Create indexes for ``table`` when a time column exists.
    Returns names of indexes created or already present (IF NOT EXISTS).

    Area partitions often have empty legacy ``cell_name``/``timestamp`` columns
    beside populated vendor axes (``LNCEL name`` / ``PERIOD_START_TIME``). Index
    every matching pair so lookups on the live axis stay index-backed.
    """
    cols = _table_columns(conn, table)
    if not cols:
        return []

    time_cols = _all_alias_cols(cols, _TIME_ALIASES)
    if not time_cols:
        return []

    created: list[str] = []
    suf = _index_suffix(table)
    cell_name_cols = _all_alias_cols(cols, _CELL_NAME_ALIASES)
    # Prefer a vendor-native cell col for id pairing when legacy cell_name is empty.
    primary_cell = next((c for c in cell_name_cols if _norm_col(c) != "cell_name"), None)
    if primary_cell is None and cell_name_cols:
        primary_cell = cell_name_cols[0]
    cell_id_col = _pick_cell_id_col(cols, primary_cell)
    group_col = _pick_from_aliases(cols, _GROUP_ALIASES)
    primary_time = time_cols[0]

    pairs: list[tuple[str, str, str]] = []

    if "cell_name" in cols and "timestamp" in cols:
        pairs.append((f"idx_{suf}_cn_ts", "cell_name", "timestamp"))

    vendor_cell_i = 0
    for cell_col in cell_name_cols:
        if _norm_col(cell_col) == "cell_name" and "timestamp" in cols:
            # Already covered by cn_ts above.
            continue
        time_for_cell = next(
            (t for t in time_cols if _norm_col(t) != "timestamp"),
            primary_time,
        )
        tag = "cell" if vendor_cell_i == 0 else f"cell{vendor_cell_i}"
        vendor_cell_i += 1
        pairs.append((f"idx_{suf}_{tag}_ts", cell_col, time_for_cell))

    if cell_id_col and cell_id_col not in cell_name_cols:
        pairs.append((f"idx_{suf}_id_ts", cell_id_col, primary_time))
    if group_col:
        pairs.append((f"idx_{suf}_grp_ts", group_col, primary_time))

    seen_pairs: set[tuple[str, str]] = set()
    for idx_name, col_a, col_b in pairs:
        key = (col_a, col_b)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        if _create_composite_index(conn, table, idx_name, col_a, col_b):
            created.append(idx_name)

    for i, time_col in enumerate(time_cols):
        ts_idx = f"idx_{suf}_ts" if i == 0 else f"idx_{suf}_ts{i}"
        if _create_single_index(conn, table, ts_idx, time_col):
            created.append(ts_idx)

    return created


def ensure_pm_database(
    db_path: str,
    *,
    label: str = "",
    analyze: bool = True,
) -> dict:
    """Ensure indexes on all PM/group tables in one SQLite file."""
    tag = label or os.path.basename(db_path)
    result: dict = {"label": tag, "path": db_path, "tables": {}, "indexes": [], "missing": False}

    if not os.path.isfile(db_path):
        result["missing"] = True
        return result

    conn = sqlite3.connect(db_path, timeout=120)
    try:
        conn.execute("PRAGMA busy_timeout=120000")
    except sqlite3.Error:
        pass
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for table in tables:
            idxs = ensure_table_indexes(conn, table)
            if idxs:
                result["tables"][table] = idxs
                result["indexes"].extend(idxs)
            if analyze:
                try:
                    conn.execute(f"ANALYZE {_quote_ident(table)}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()
    finally:
        conn.close()
    return result


def _pm_db_paths(*, scope: str = "hourly", categories: tuple[str, ...] = ("cells", "groups")) -> list[tuple[str, str]]:
    from sync_config import (
        HUAWEI_GROUPS_DAILY_DB,
        HUAWEI_GROUPS_DB,
        HUAWEI_PM_DAILY_DB,
        HUAWEI_PM_DB,
        NOKIA_GROUPS_DAILY_DB,
        NOKIA_GROUPS_DB,
        NOKIA_PM_DAILY_DB,
        NOKIA_PM_DB,
    )

    is_daily = str(scope).lower() == "daily"
    out: list[tuple[str, str]] = []
    if "cells" in categories:
        out.append(
            ("Nokia PM cells", NOKIA_PM_DAILY_DB if is_daily else NOKIA_PM_DB)
        )
        out.append(
            ("Huawei PM cells", HUAWEI_PM_DAILY_DB if is_daily else HUAWEI_PM_DB)
        )
    if "groups" in categories:
        out.append(
            ("Nokia groups", NOKIA_GROUPS_DAILY_DB if is_daily else NOKIA_GROUPS_DB)
        )
        out.append(
            ("Huawei groups", HUAWEI_GROUPS_DAILY_DB if is_daily else HUAWEI_GROUPS_DB)
        )
    return out


def ensure_all_pm_databases(
    *,
    scope: str = "hourly",
    categories: tuple[str, ...] = ("cells", "groups"),
    analyze: bool = True,
) -> dict:
    """Ensure indexes on all configured Nokia/Huawei PM and group databases."""
    reports: list[dict] = []
    messages: list[str] = []
    for label, path in _pm_db_paths(scope=scope, categories=categories):
        rep = ensure_pm_database(path, label=label, analyze=analyze)
        reports.append(rep)
        if rep.get("missing"):
            messages.append(f"[pm-indexes] {label}: missing file")
            continue
        n_tables = len(rep.get("tables") or {})
        n_idx = len(rep.get("indexes") or [])
        messages.append(f"[pm-indexes] {label}: {n_tables} table(s), {n_idx} index(es) ensured")
    return {"scope": scope, "categories": list(categories), "reports": reports, "messages": messages}
