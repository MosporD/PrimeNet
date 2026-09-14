"""Query helpers for Performance Explorer Plus APIs."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from core.pm_plus.db import connect, execute, fetchall, fetchone, qident
from core.pm_plus.kpi_compiler import completeness, eval_formula, formula_tokens, validate_formula
from core.pm_plus.schema import init_schema


def _fact_table(resolution: str) -> str:
    r = (resolution or "hour").lower()
    if r in ("15m", "15", "rop"):
        return "fact_values_15m"
    if r in ("day", "daily", "d"):
        return "fact_values_day"
    return "fact_values_hour"


def list_counters(*, q: str = "", limit: int = 200) -> list[dict]:
    init_schema()
    t = qident("dim_counter")
    params: list = []
    sql = f"SELECT counter_id, family, display_name, agg_rule, vendor FROM {t}"
    if q:
        sql += " WHERE counter_id LIKE ? OR IFNULL(display_name,'') LIKE ? OR IFNULL(family,'') LIKE ?"
        like = f"%{q}%"
        params.extend([like, like, like])
    sql += " ORDER BY counter_id LIMIT ?"
    params.append(limit)
    with connect() as conn:
        # SQLite has IFNULL; Postgres prefers COALESCE — use COALESCE
        sql = sql.replace("IFNULL", "COALESCE")
        return fetchall(conn, sql, tuple(params))


def list_objects(*, q: str = "", limit: int = 200) -> list[dict]:
    init_schema()
    t = qident("dim_object")
    params: list = []
    sql = (
        f"SELECT object_dn, tech, ne_type, mo_class, site_key, controller_key, vendor "
        f"FROM {t}"
    )
    if q:
        sql += (
            " WHERE object_dn LIKE ? OR COALESCE(site_key,'') LIKE ? "
            "OR COALESCE(ne_type,'') LIKE ? OR COALESCE(mo_class,'') LIKE ?"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql += " ORDER BY object_dn LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return fetchall(conn, sql, tuple(params))


def list_families(*, ne_type: str | None = None, limit: int = 500) -> list[dict]:
    init_schema()
    t = qident("dim_family")
    params: list = []
    sql = f"SELECT family, vendor, ne_type, default_gp_seconds FROM {t}"
    if ne_type:
        sql += " WHERE ne_type = ?"
        params.append(ne_type.upper())
    sql += " ORDER BY family LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return fetchall(conn, sql, tuple(params))


def query_series(
    *,
    counter_ids: list[str] | None = None,
    formula: str | None = None,
    object_dns: list[str] | None = None,
    site_key: str | None = None,
    resolution: str = "hour",
    ts_from: str | None = None,
    ts_to: str | None = None,
    gp_seconds: int | None = 900,
    ne_type: str | None = None,
    stream: str | None = None,
    limit: int = 5000,
) -> dict:
    """
    Return time series for raw counters or a KPI formula.

    Grain filters (defaults keep aggregations clean):
    - gp_seconds: native ROP length (default 900). Pass None to include all grains.
    - ne_type / stream: optional; omit to include all.

    Completeness = distinct objects with data / expected objects in filter.
    """
    init_schema()
    table = qident(_fact_table(resolution))
    tobj = qident("dim_object")
    tokens = formula_tokens(formula) if formula else list(counter_ids or [])
    if not tokens:
        return {"points": [], "completeness_pct": None, "error": "No counters or formula provided"}

    where = ["counter_id IN ({})".format(",".join("?" * len(tokens)))]
    params: list = list(tokens)
    if object_dns:
        where.append("object_dn IN ({})".format(",".join("?" * len(object_dns))))
        params.extend(object_dns)
    if site_key:
        where.append(
            f"object_dn IN (SELECT object_dn FROM {tobj} WHERE site_key=?)"
        )
        params.append(site_key)
    if gp_seconds is not None:
        where.append("gp_seconds = ?")
        params.append(int(gp_seconds))
    if ne_type:
        where.append("ne_type = ?")
        params.append(ne_type.upper())
    if stream:
        where.append("stream = ?")
        params.append(stream)
    if ts_from:
        where.append("bucket_ts >= ?")
        params.append(ts_from)
    if ts_to:
        where.append("bucket_ts <= ?")
        params.append(ts_to)

    sql = (
        f"SELECT bucket_ts, object_dn, counter_id, value, gp_seconds, ne_type, stream, family "
        f"FROM {table} "
        f"WHERE {' AND '.join(where)} ORDER BY bucket_ts, object_dn LIMIT ?"
    )
    params.append(limit)

    with connect() as conn:
        rows = fetchall(conn, sql, tuple(params))
        expected = None
        if site_key:
            er = fetchone(conn, f"SELECT COUNT(*) AS n FROM {tobj} WHERE site_key=?", (site_key,))
            expected = int(er["n"]) if er else None
        elif object_dns:
            expected = len(object_dns)

    # Pivot by (ts, object) then evaluate
    by_key: dict[tuple[str, str], dict[str, float | None]] = {}
    objects_seen: set[str] = set()
    for r in rows:
        ts = str(r["bucket_ts"])
        odn = r["object_dn"]
        objects_seen.add(odn)
        slot = by_key.setdefault((ts, odn), {})
        slot[r["counter_id"]] = r["value"]

    points = []
    if formula:
        for (ts, odn), cmap in sorted(by_key.items()):
            points.append(
                {
                    "bucket_ts": ts,
                    "object_dn": odn,
                    "value": eval_formula(formula, cmap),
                    "counters": cmap,
                }
            )
    else:
        for (ts, odn), cmap in sorted(by_key.items()):
            for cid, val in cmap.items():
                points.append(
                    {
                        "bucket_ts": ts,
                        "object_dn": odn,
                        "counter_id": cid,
                        "value": val,
                    }
                )

    # Aggregate to network/site series if many objects — also provide summary by ts
    by_ts: dict[str, list[float]] = {}
    for p in points:
        if p.get("value") is None:
            continue
        by_ts.setdefault(p["bucket_ts"], []).append(float(p["value"]))
    summary = [
        {
            "bucket_ts": ts,
            "value": (sum(vals) / len(vals)) if formula else sum(vals),
            "n": len(vals),
        }
        for ts, vals in sorted(by_ts.items())
    ]

    return {
        "points": points[:limit],
        "summary": summary,
        "completeness_pct": completeness(expected or 0, len(objects_seen)) if expected else None,
        "objects_with_data": len(objects_seen),
        "expected_objects": expected,
        "resolution": resolution,
        "formula": formula,
        "counters": tokens,
    }


def list_kpis() -> list[dict]:
    init_schema()
    with connect() as conn:
        return fetchall(
            conn,
            f"SELECT id, name, formula, description, vendor, scope_default, created_by, created_at "
            f"FROM {qident('kpi_definitions')} ORDER BY name",
        )


def save_kpi(
    *,
    name: str,
    formula: str,
    description: str = "",
    created_by: str = "",
    scope_default: str = "cell",
) -> dict:
    init_schema()
    v = validate_formula(formula)
    if not v["ok"]:
        return {"ok": False, "errors": v["errors"]}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t = qident("kpi_definitions")
    with connect() as conn:
        existing = fetchone(conn, f"SELECT id FROM {t} WHERE name=?", (name,))
        if existing:
            execute(
                conn,
                f"UPDATE {t} SET formula=?, description=?, scope_default=?, updated_at=? WHERE id=?",
                (formula, description, scope_default, now, existing["id"]),
            )
            kid = existing["id"]
        else:
            execute(
                conn,
                f"INSERT INTO {t} (name, formula, description, vendor, scope_default, created_by, created_at, updated_at) "
                f"VALUES (?,?,?,?,?,?,?,?)",
                (name, formula, description, "nokia", scope_default, created_by, now, now),
            )
            row = fetchone(conn, f"SELECT id FROM {t} WHERE name=?", (name,))
            kid = row["id"] if row else None
        conn.commit()
    return {"ok": True, "id": kid, "warnings": v.get("warnings") or []}


def delete_kpi(kpi_id: int) -> bool:
    init_schema()
    with connect() as conn:
        execute(conn, f"DELETE FROM {qident('kpi_definitions')} WHERE id=?", (kpi_id,))
        conn.commit()
    return True


def list_saved_views() -> list[dict]:
    init_schema()
    with connect() as conn:
        rows = fetchall(
            conn,
            f"SELECT id, name, payload_json, created_by, created_at FROM {qident('saved_views')} ORDER BY name",
        )
    for r in rows:
        try:
            r["payload"] = json.loads(r.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            r["payload"] = {}
    return rows


def save_view(*, name: str, payload: dict, created_by: str = "") -> dict:
    init_schema()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    blob = json.dumps(payload)
    t = qident("saved_views")
    with connect() as conn:
        existing = fetchone(conn, f"SELECT id FROM {t} WHERE name=?", (name,))
        if existing:
            execute(
                conn,
                f"UPDATE {t} SET payload_json=?, updated_at=? WHERE id=?",
                (blob, now, existing["id"]),
            )
            vid = existing["id"]
        else:
            execute(
                conn,
                f"INSERT INTO {t} (name, payload_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?)",
                (name, blob, created_by, now, now),
            )
            row = fetchone(conn, f"SELECT id FROM {t} WHERE name=?", (name,))
            vid = row["id"] if row else None
        conn.commit()
    return {"ok": True, "id": vid}


def export_series_csv(result: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["bucket_ts", "object_dn", "counter_id", "value"])
    for p in result.get("points") or []:
        w.writerow(
            [
                p.get("bucket_ts"),
                p.get("object_dn"),
                p.get("counter_id") or (result.get("formula") or "kpi"),
                p.get("value"),
            ]
        )
    return buf.getvalue()


def warehouse_stats() -> dict:
    init_schema()
    with connect() as conn:
        def count(table: str) -> int:
            r = fetchone(conn, f"SELECT COUNT(*) AS n FROM {qident(table)}")
            return int(r["n"]) if r else 0

        grain_rows = fetchall(
            conn,
            f"SELECT gp_seconds, ne_type, stream, COUNT(*) AS n "
            f"FROM {qident('fact_values_15m')} "
            f"GROUP BY gp_seconds, ne_type, stream "
            f"ORDER BY n DESC LIMIT 50",
        )
        return {
            "objects": count("dim_object"),
            "counters": count("dim_counter"),
            "families": count("dim_family"),
            "fact_15m": count("fact_values_15m"),
            "fact_hour": count("fact_values_hour"),
            "fact_day": count("fact_values_day"),
            "kpis": count("kpi_definitions"),
            "ledger": count("ingest_ledger"),
            "rop_grain_breakdown": [
                {
                    "gp_seconds": r["gp_seconds"],
                    "ne_type": r["ne_type"],
                    "stream": r["stream"],
                    "rows": int(r["n"]),
                }
                for r in grain_rows
            ],
        }
