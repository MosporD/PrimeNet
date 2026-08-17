"""Group / controller PM scans for Network Health and Group Health."""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from sync_config import (
    HUAWEI_GROUPS_DAILY_DB,
    HUAWEI_GROUPS_DB,
    NOKIA_GROUPS_DAILY_DB,
    NOKIA_GROUPS_DB,
    pm_table_name,
)

from .scoring import bounded_score, issue, summarize, to_float, utc_now_iso

GROUP_NAME_ALIASES = (
    "group name",
    "bsc name",
    "rnc name",
    "controller",
    "bsc",
    "rnc",
    "enb name",
    "gnb name",
    "name",
)
UTIL_ALIASES = (
    "dl prb usage rate(%)",
    "prb util pdsch",
    "e-utran avg prb usage per tti dl",
    "utilization",
    "prb",
)
TRAFFIC_ALIASES = ("traffic volume", "payload", "data volume", "pdcp sdu volume")
USERS_ALIASES = ("average user number", "avg act ues", "active users", "users")


def _connect(path: str) -> sqlite3.Connection | None:
    if not path or not os.path.isfile(path):
        return None
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return [str(r[0]) for r in rows if r[0] and not str(r[0]).startswith("sqlite_")]


def _pick_col(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    lower = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    for low, col in lower.items():
        if any(alias in low or low in alias for alias in aliases if len(alias) >= 3):
            return col
    return None


def _vendor_sources(vendor: str) -> list[tuple[str, str, str]]:
    v = (vendor or "all").strip().lower()
    out: list[tuple[str, str, str]] = []
    if v in ("all", "nokia"):
        out.append(("Nokia", NOKIA_GROUPS_DAILY_DB, NOKIA_GROUPS_DB))
    if v in ("all", "huawei"):
        out.append(("Huawei", HUAWEI_GROUPS_DAILY_DB, HUAWEI_GROUPS_DB))
    return out


def group_db_inventory() -> list[dict[str, Any]]:
    rows = []
    for label, daily, hourly in (
        ("Nokia groups daily", NOKIA_GROUPS_DAILY_DB, None),
        ("Nokia groups hourly", NOKIA_GROUPS_DB, None),
        ("Huawei groups daily", HUAWEI_GROUPS_DAILY_DB, None),
        ("Huawei groups hourly", HUAWEI_GROUPS_DB, None),
    ):
        path = daily or hourly
        exists = os.path.isfile(path)
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 2) if exists else 0
        tables = []
        if exists:
            conn = _connect(path)
            if conn is not None:
                try:
                    tables = _tables(conn)
                finally:
                    conn.close()
        rows.append({
            "label": label,
            "path": path,
            "exists": exists,
            "size_mb": size_mb,
            "tables": tables,
        })
    return rows


def _scan_table(conn: sqlite3.Connection, table: str, vendor: str, technology: str, limit: int) -> list[dict]:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    name_col = _pick_col(cols, GROUP_NAME_ALIASES)
    kpi_col = (
        _pick_col(cols, UTIL_ALIASES)
        or _pick_col(cols, USERS_ALIASES)
        or _pick_col(cols, TRAFFIC_ALIASES)
    )
    if not name_col or not kpi_col:
        return []
    ident_name = '"' + name_col.replace('"', '""') + '"'
    ident_kpi = '"' + kpi_col.replace('"', '""') + '"'
    ident_table = '"' + table.replace('"', '""') + '"'
    sql = (
        f"SELECT {ident_name} AS grp, {ident_kpi} AS kpi_val "
        f"FROM {ident_table} WHERE {ident_kpi} IS NOT NULL "
        f"ORDER BY rowid DESC LIMIT {max(200, limit * 20)}"
    )
    try:
        raw = conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    best: dict[str, float] = {}
    for row in raw:
        grp = str(row["grp"] or "").strip()
        val = to_float(row["kpi_val"])
        if not grp or val is None:
            continue
        if grp not in best or val > best[grp]:
            best[grp] = val
    issues = []
    for grp, val in sorted(best.items(), key=lambda kv: -kv[1])[:limit]:
        score = bounded_score(min(90.0, val))
        if score < 20:
            continue
        issues.append(issue(
            module="Group Health",
            category="Controller / Cluster",
            title=f"{vendor} {technology} group pressure: {grp}",
            summary=f"{kpi_col} latest={round(val, 2)} on group/controller '{grp}'.",
            score=score,
            cells=[],
            site_id=grp,
            vendor=vendor,
            technology=technology,
            evidence={"group": grp, "kpi": kpi_col, "value": round(val, 3), "table": table},
            recommendation="Open Performance Explorer in group mode and drill into the worst cells inside this controller.",
            source_url="/group-health",
        ))
    return issues


def group_health(*, vendor: str = "all", technology: str = "all", limit: int = 200) -> dict:
    techs = ["2G", "3G", "4G", "5G"] if technology in ("", "all", None) else [str(technology).split("-")[0].upper()]
    issues: list[dict] = []
    scanned = 0
    for vlabel, daily, hourly in _vendor_sources(vendor):
        for tech in techs:
            table = pm_table_name(tech, scope="daily")
            conn = _connect(daily) or _connect(hourly)
            if conn is None:
                continue
            try:
                tables = _tables(conn)
                candidates = [table] if table in tables else [t for t in tables if tech in t.upper()]
                if not candidates:
                    candidates = tables[:2]
                for tbl in candidates[:3]:
                    scanned += 1
                    issues.extend(_scan_table(conn, tbl, vlabel, tech, limit))
            finally:
                conn.close()
    issues.sort(key=lambda r: -float(r.get("score") or 0))
    issues = issues[: max(1, int(limit))]
    return {
        "generated_at": utc_now_iso(),
        "summary": summarize(issues),
        "issues": issues,
        "inventory": group_db_inventory(),
        "scanned_tables": scanned,
        "note": "Group DBs are controller/BSC/RNC aggregates — cell detectors miss this congestion.",
    }
