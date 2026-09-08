"""Neighbor-graph aggregates for SON ML — SQL over vendor 4G export tables.

Does not use the map-line sampler (`load_neighbor_lines`). That path caps rows,
requires coordinates, and keys Huawei PM by LocalCell Id unless SON remaps it.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections import defaultdict

from db.runtime import open_db, store_available
from modules.network_map.neighbor_raw_linking import (
    _normalize_ho_success_rate_percent,
    _pick_column,
    _to_float,
    _to_int,
)
from sync_config import HUAWEI_NEIGHBOR_RAW_DB, METADATA_DB, NEIGHBOR_KPI_DB

from . import config as cfg

logger = logging.getLogger(__name__)

_BAD = frozenset(("", "nan", "none", "null", "none"))


def _norm_key(value: object) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _display_name(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.Error:
        return []


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _scan_pairs(
    conn: sqlite3.Connection,
    table: str,
    src_col: str,
    tgt_col: str,
    att_col: str | None,
    succ_col: str | None,
    sr_col: str | None,
    extra_att_col: str | None = None,
    extra_sr_col: str | None = None,
) -> list[tuple[str, str, str, str, float, float | None]]:
    """Return (src_key, tgt_key, src_display, tgt_display, attempts, sr_percent)."""
    cols = _table_columns(conn, table)
    if src_col not in cols or tgt_col not in cols:
        return []
    select = [src_col, tgt_col]
    for col in (att_col, succ_col, sr_col, extra_att_col, extra_sr_col):
        if col and col in cols:
            select.append(col)
    select = list(dict.fromkeys(select))
    sql = "SELECT " + ", ".join(f'"{c}"' for c in select) + f' FROM "{table}"'
    out: list[tuple[str, str, str, str, float, float | None]] = []
    min_att = float(cfg.NEIGHBOR_MIN_ATTEMPTS)
    try:
        rows = conn.execute(sql)
    except sqlite3.Error:
        logger.exception("SON neighbor scan failed for %s", table)
        return []
    for row in rows:
        src_raw = row[src_col]
        tgt_raw = row[tgt_col]
        src_key = _norm_key(src_raw)
        tgt_key = _norm_key(tgt_raw)
        if not src_key or not tgt_key or src_key in _BAD or tgt_key in _BAD:
            continue
        att = 0.0
        if att_col and att_col in cols:
            att += _to_float(row[att_col]) or 0.0
        if extra_att_col and extra_att_col in cols:
            att += _to_float(row[extra_att_col]) or 0.0
        if att < min_att:
            continue
        sr: float | None = None
        if sr_col and sr_col in cols:
            sr = _normalize_ho_success_rate_percent(row[sr_col])
        if extra_sr_col and extra_sr_col in cols and sr is None:
            sr = _normalize_ho_success_rate_percent(row[extra_sr_col])
        if succ_col and succ_col in cols and sr is None:
            succ = _to_float(row[succ_col])
            if succ is not None and att > 0:
                sr = max(0.0, min(100.0, 100.0 * succ / att))
        out.append(
            (
                src_key,
                tgt_key,
                _display_name(src_raw, src_key),
                _display_name(tgt_raw, tgt_key),
                att,
                sr,
            )
        )
    return out


def _huawei_4g_pairs(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, float, float | None]]:
    table = "huawei_neighbor_export_4g"
    if not _table_exists(conn, table):
        return []
    cols = _table_columns(conn, table)
    src = _pick_column(cols, "Local_cell_name", "local_cell_name", "Cell_Name", "cell_name")
    tgt = _pick_column(cols, "Target_Cell_Name", "target_cell_name", "DEST_Cell_Name")
    att = _pick_column(cols, "L_HHO_NCell_ExecAttOut")
    succ = _pick_column(cols, "L_HHO_NCell_ExecSuccOut")
    if not src or not tgt:
        return []
    return _scan_pairs(conn, table, src, tgt, att, succ, None)


def _nokia_eci_to_cell_name() -> dict[int, str]:
    """ECI (eNB*256 + cell_id) -> metadata cell_name. Nokia 4G exports leave Target LNCEL empty."""
    if not store_available(METADATA_DB):
        return {}
    out: dict[int, str] = {}
    meta = open_db(METADATA_DB, timeout=30)
    try:
        tables = [
            r[0]
            for r in meta.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('cells_4g_fdd','cells_4g_tdd')"
            )
        ]
        for table in tables:
            cols = _table_columns(meta, table)
            if "cell_name" not in cols or "enb_id_actual" not in cols or "cell_id" not in cols:
                continue
            for row in meta.execute(
                f'SELECT cell_name, enb_id_actual, cell_id FROM "{table}"'
            ):
                name = str(row[0] or "").strip()
                enb = _to_int(row[1])
                cid = _to_int(row[2])
                if not name or enb is None or cid is None:
                    continue
                eci = enb * 256 + (cid % 256)
                out.setdefault(eci, name)
    except sqlite3.Error:
        logger.exception("SON Nokia ECI map failed")
    finally:
        meta.close()
    logger.info("SON Nokia ECI map: %s cells", len(out))
    return out


def _nokia_4g_pairs(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, float, float | None]]:
    table = "nokia_neighbor_4g"
    if not _table_exists(conn, table):
        return []
    cols = _table_columns(conn, table)
    src = _pick_column(
        cols,
        "Source_LNCEL_name",
        "source_lncel_name",
        "SourceLNCELName",
    )
    tgt_name = _pick_column(
        cols,
        "Target_LNCEL_name",
        "target_lncel_name",
        "TargetLNCELName",
    )
    eci_col = _pick_column(cols, "eci_id", "ECI", "Eci")
    intra_att = _pick_column(cols, "Intra_eNB_HO_attempts_per_neighbor_cell")
    intra_sr = _pick_column(cols, "Adj_Intra_eNB_HO_SR")
    inter_att = _pick_column(
        cols,
        "Number_of_Inter_eNB_Handover_attempts_per_neighbor_cell_relationship",
    )
    inter_sr = _pick_column(cols, "Adj_Inter_eNB_HO_SR")
    if not src:
        return []
    att_sql_parts: list[str] = []
    if intra_att:
        att_sql_parts.append(f'COALESCE(CAST("{intra_att}" AS REAL), 0)')
    if inter_att:
        att_sql_parts.append(f'COALESCE(CAST("{inter_att}" AS REAL), 0)')
    if not att_sql_parts:
        return []
    att_expr = " + ".join(att_sql_parts)
    if intra_sr and intra_att:
        inter_att_col = inter_att or intra_att
        inter_sr_col = inter_sr or intra_sr
        sr_expr = (
            f'SUM(COALESCE(CAST("{intra_att}" AS REAL), 0) * COALESCE(CAST("{intra_sr}" AS REAL), 0) '
            f'+ COALESCE(CAST("{inter_att_col}" AS REAL), 0) * COALESCE(CAST("{inter_sr_col}" AS REAL), 0))'
        )
    else:
        sr_expr = "NULL"
    tgt_select = f'"{tgt_name}"' if tgt_name else "NULL"
    eci_select = f'"{eci_col}"' if eci_col else "NULL"
    sql = f"""
        SELECT "{src}" AS src, {tgt_select} AS tgt_name, {eci_select} AS eci,
               SUM({att_expr}) AS att, {sr_expr} AS sr_weighted
        FROM "{table}"
        GROUP BY "{src}", {tgt_select}, {eci_select}
        HAVING SUM({att_expr}) >= ?
    """
    eci_map = _nokia_eci_to_cell_name() if eci_col else {}
    min_att = float(cfg.NEIGHBOR_MIN_ATTEMPTS)
    out: list[tuple[str, str, str, str, float, float | None]] = []
    try:
        rows = conn.execute(sql, (min_att,))
    except sqlite3.Error:
        logger.exception("SON Nokia 4G neighbor aggregate failed")
        return []
    for row in rows:
        src_raw = row[0]
        src_key = _norm_key(src_raw)
        if not src_key or src_key in _BAD:
            continue
        tgt_raw = row[1]
        tgt_key = _norm_key(tgt_raw)
        if not tgt_key or tgt_key in _BAD:
            eci_val = _to_int(row[2])
            resolved = eci_map.get(eci_val) if eci_val is not None else None
            if not resolved:
                continue
            tgt_raw = resolved
            tgt_key = _norm_key(resolved)
        att = float(row[3] or 0)
        if att < min_att:
            continue
        sr = None
        if row[4] is not None and att > 0:
            sr = _normalize_ho_success_rate_percent(float(row[4]) / att)
        out.append(
            (
                src_key,
                tgt_key,
                _display_name(src_raw, src_key),
                _display_name(tgt_raw, tgt_key),
                att,
                sr,
            )
        )
    return out


def load_neighbor_pairs(vendor: str) -> list[tuple[str, str, str, str, float, float | None]]:
    vkey = (vendor or "").strip().lower()
    if vkey == "huawei":
        path = HUAWEI_NEIGHBOR_RAW_DB
        loader = _huawei_4g_pairs
    elif vkey == "nokia":
        path = NEIGHBOR_KPI_DB
        loader = _nokia_4g_pairs
    else:
        return []
    if not store_available(path):
        return []
    conn = open_db(path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        pairs = loader(conn)
    finally:
        conn.close()
    logger.info("SON neighbor pairs %s: %s relations", vkey, len(pairs))
    return pairs


def aggregate_pairs(
    pairs: list[tuple[str, str, str, str, float, float | None]],
) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
    """Roll relation rows into per-source stats + adjacency (target keys, attempt-ranked)."""
    pair_set = {(src, tgt) for src, tgt, _sd, _td, _a, _sr in pairs if src and tgt}
    buckets: dict[str, list[tuple[str, str, float, float | None]]] = defaultdict(list)
    display: dict[str, str] = {}
    for src, tgt, src_disp, tgt_disp, att, sr in pairs:
        buckets[src].append((tgt, tgt_disp, att, sr))
        display[src] = src_disp
        display.setdefault(tgt, tgt_disp)

    stats: dict[str, dict[str, float]] = {}
    adj: dict[str, list[str]] = {}
    cap = max(4, int(cfg.NEIGHBOR_MAX_PER_CELL))
    for src, items in buckets.items():
        by_tgt: dict[str, list[tuple[float, float | None]]] = defaultdict(list)
        for tgt, _td, att, sr in items:
            by_tgt[tgt].append((att, sr))
        ranked: list[tuple[str, float, float | None]] = []
        for tgt, parts in by_tgt.items():
            att_sum = sum(a for a, _s in parts)
            sr_parts = [(a, s) for a, s in parts if s is not None]
            if sr_parts:
                w = sum(a for a, _s in sr_parts) or 1.0
                sr_val = sum(a * s for a, s in sr_parts) / w
            else:
                sr_val = None
            ranked.append((tgt, att_sum, sr_val))
        ranked.sort(key=lambda r: -r[1])
        kept = ranked[:cap]
        n = len(kept)
        if n == 0:
            continue
        attempts = [r[1] for r in kept]
        srs = [r[2] for r in kept if r[2] is not None]
        missing = 0.0
        for tgt, _att, _sr in kept:
            if (tgt, src) not in pair_set:
                missing += 1.0
        name = display.get(src, src)
        payload = {
            "nbr_count": float(n),
            "nbr_ho_attempts": sum(attempts) / n,
            "nbr_ho_sr": sum(srs) / len(srs) if srs else 0.0,
            "nbr_distance_km": 0.0,
            "nbr_missing_recip": missing / n,
        }
        stats[src] = payload
        stats[name.lower()] = payload
        adj[src] = [tgt for tgt, _a, _sr in kept]
        adj[name.lower()] = adj[src]
    return stats, adj


def neighbor_stats(vendor: str, technology: str = "4G-4G") -> dict[str, dict[str, float]]:
    _ = technology
    stats, _adj = aggregate_pairs(load_neighbor_pairs(vendor))
    return stats


def neighbor_adjacency(vendor: str, technology: str = "4G-4G") -> dict[str, list[str]]:
    _ = technology
    adj, _stats = neighbor_adjacency_and_stats(vendor)
    return adj


def neighbor_adjacency_and_stats(
    vendor: str,
) -> tuple[dict[str, list[str]], dict[str, dict[str, float]]]:
    stats, adj = aggregate_pairs(load_neighbor_pairs(vendor))
    return adj, stats


def attach_neighbor_features(
    rows: list[dict],
    vendor: str,
    *,
    stats: dict[str, dict[str, float]] | None = None,
    adj: dict[str, list[str]] | None = None,
) -> None:
    if stats is None or adj is None:
        loaded_stats, loaded_adj = aggregate_pairs(load_neighbor_pairs(vendor))
        stats = loaded_stats if stats is None else stats
        adj = loaded_adj if adj is None else adj
    loc: dict[str, tuple[float, float]] = {}
    for row in rows:
        key = _norm_key(row.get("cell_name"))
        if not key:
            continue
        try:
            lat = float(row.get("latitude"))
            lng = float(row.get("longitude"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(lat) or not math.isfinite(lng):
            continue
        loc[key] = (lat, lng)

    matched = 0
    for row in rows:
        key = _norm_key(row.get("cell_name"))
        info = stats.get(key) or {}
        if info:
            matched += 1
        row["nbr_count"] = info.get("nbr_count", 0.0)
        row["nbr_ho_attempts"] = info.get("nbr_ho_attempts", 0.0)
        row["nbr_ho_sr"] = info.get("nbr_ho_sr", 0.0)
        row["nbr_missing_recip"] = info.get("nbr_missing_recip", 0.0)
        dists: list[float] = []
        src_ll = loc.get(key)
        if src_ll:
            for tgt in adj.get(key) or []:
                tgt_ll = loc.get(tgt)
                if not tgt_ll:
                    continue
                try:
                    dists.append(_haversine_km(src_ll[0], src_ll[1], tgt_ll[0], tgt_ll[1]))
                except Exception:
                    continue
        row["nbr_distance_km"] = sum(dists) / len(dists) if dists else 0.0
    logger.info(
        "SON neighbor attach %s: %s/%s cell-days matched",
        vendor,
        matched,
        len(rows),
    )
