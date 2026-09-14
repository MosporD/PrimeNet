"""Rule-aware rollups for PM Plus.

Cascade (locked):
  hour  ← raw ROP (fact_values_15m)
  day   ← raw ROP (fact_values_15m)   # not from hour — AVG-safe
  week  ← day
  month ← week
  year  ← month
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.pm_plus import config
from core.pm_plus.agg_rules import AggParts, load_time_agg_map, normalize_agg_rule
from core.pm_plus.db import connect, execute, fetchall, qident
from core.pm_plus.schema import init_schema

_CONFLICT = "bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hour_floor(ts: str) -> str:
    dt = _parse_ts(ts).replace(minute=0, second=0, microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def day_floor(ts: str) -> str:
    dt = _parse_ts(ts).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def week_floor(ts: str) -> str:
    """ISO week start (Monday 00:00 UTC)."""
    dt = _parse_ts(ts).replace(hour=0, minute=0, second=0, microsecond=0)
    dt = dt - timedelta(days=dt.weekday())
    return dt.isoformat().replace("+00:00", "Z")


def month_floor(ts: str) -> str:
    dt = _parse_ts(ts).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def year_floor(ts: str) -> str:
    dt = _parse_ts(ts).replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def _fold_rows(
    rows: list,
    *,
    bucket_fn,
    rule_map: dict[str, str],
) -> dict[tuple, dict]:
    folded: dict[tuple, AggParts] = {}
    meta: dict[tuple, dict] = {}
    for r in rows:
        cid = r["counter_id"]
        gp = int(r.get("gp_seconds") or 900)
        ne = (r.get("ne_type") or "").upper()
        stream = r.get("stream") or ""
        bucket = bucket_fn(str(r["bucket_ts"]))
        key = (bucket, r["object_dn"], cid, gp, ne, stream)
        slot = folded.get(key)
        if slot is None:
            slot = AggParts(family=r.get("family") or "", vendor=r.get("vendor") or "nokia")
            folded[key] = slot
            meta[key] = {
                "bucket_ts": bucket,
                "object_dn": r["object_dn"],
                "counter_id": cid,
                "gp_seconds": gp,
                "ne_type": ne,
                "stream": stream,
                "family": r.get("family"),
                "vendor": r.get("vendor") or "nokia",
            }
        rule = rule_map.get(cid, "SUM")
        val = r["value"]
        sc = float(r.get("sample_count") or 1)
        if val is None:
            continue
        if normalize_agg_rule(rule) == "AVG":
            slot.add(float(val), weight=sc)
        else:
            # SUM/MAX/MIN: each source row is one part (weight 1 for SUM add)
            if normalize_agg_rule(rule) == "SUM":
                slot.add(float(val), weight=1.0)
            else:
                slot.add(float(val), weight=1.0)

    out: dict[tuple, dict] = {}
    for key, parts in folded.items():
        rule = rule_map.get(key[2], "SUM")
        value, sc = parts.finish(rule)
        if value is None:
            continue
        row = dict(meta[key])
        row["value"] = value
        row["sample_count"] = sc
        row["family"] = parts.family or row.get("family")
        out[key] = row
    return out


def _upsert_facts(conn, table: str, rows: dict[tuple, dict]) -> int:
    n = 0
    for row in rows.values():
        execute(
            conn,
            f"INSERT INTO {table} "
            f"(bucket_ts, object_dn, counter_id, gp_seconds, ne_type, stream, family, value, vendor, sample_count) "
            f"VALUES (?,?,?,?,?,?,?,?,?,?) "
            f"ON CONFLICT({_CONFLICT}) DO UPDATE SET "
            f"value=excluded.value, sample_count=excluded.sample_count, family=excluded.family",
            (
                row["bucket_ts"],
                row["object_dn"],
                row["counter_id"],
                row["gp_seconds"],
                row["ne_type"],
                row["stream"],
                row.get("family"),
                row["value"],
                row["vendor"],
                row["sample_count"],
            ),
        )
        n += 1
    return n


def _load_source(
    conn,
    table: str,
    *,
    ts_from: str | None = None,
    ts_to: str | None = None,
) -> list:
    params: list = []
    where = []
    if ts_from:
        where.append("bucket_ts >= ?")
        params.append(ts_from)
    if ts_to:
        where.append("bucket_ts < ?")
        params.append(ts_to)
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    return fetchall(
        conn,
        f"SELECT bucket_ts, object_dn, family, counter_id, value, vendor, "
        f"sample_count, gp_seconds, ne_type, stream FROM {table}{wh}",
        tuple(params),
    )


def rollup_rop_to_hour(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    """Hour ← raw ROP."""
    init_schema()
    with connect() as conn:
        rows = _load_source(conn, "fact_values_15m", ts_from=ts_from, ts_to=ts_to)
        rules = load_time_agg_map({r["counter_id"] for r in rows})
        folded = _fold_rows(rows, bucket_fn=hour_floor, rule_map=rules)
        n = _upsert_facts(conn, "fact_values_hour", folded)
        conn.commit()
    return {"hour_rows_upserted": n}


def rollup_rop_to_day(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    """Day ← raw ROP (not from hour)."""
    init_schema()
    with connect() as conn:
        rows = _load_source(conn, "fact_values_15m", ts_from=ts_from, ts_to=ts_to)
        rules = load_time_agg_map({r["counter_id"] for r in rows})
        folded = _fold_rows(rows, bucket_fn=day_floor, rule_map=rules)
        n = _upsert_facts(conn, "fact_values_day", folded)
        conn.commit()
    return {"daily_rows_upserted": n}


def rollup_hour_to_day(*, day_from: str | None = None, day_to: str | None = None) -> dict:
    """Back-compat name — now day←ROP."""
    return rollup_rop_to_day(ts_from=day_from, ts_to=day_to)


def rollup_day_to_week(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    init_schema()
    with connect() as conn:
        rows = _load_source(conn, "fact_values_day", ts_from=ts_from, ts_to=ts_to)
        rules = load_time_agg_map({r["counter_id"] for r in rows})
        folded = _fold_rows(rows, bucket_fn=week_floor, rule_map=rules)
        n = _upsert_facts(conn, "fact_values_week", folded)
        conn.commit()
    return {"week_rows_upserted": n}


def rollup_week_to_month(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    init_schema()
    with connect() as conn:
        rows = _load_source(conn, "fact_values_week", ts_from=ts_from, ts_to=ts_to)
        rules = load_time_agg_map({r["counter_id"] for r in rows})
        folded = _fold_rows(rows, bucket_fn=month_floor, rule_map=rules)
        n = _upsert_facts(conn, "fact_values_month", folded)
        conn.commit()
    return {"month_rows_upserted": n}


def rollup_month_to_year(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    init_schema()
    with connect() as conn:
        rows = _load_source(conn, "fact_values_month", ts_from=ts_from, ts_to=ts_to)
        rules = load_time_agg_map({r["counter_id"] for r in rows})
        folded = _fold_rows(rows, bucket_fn=year_floor, rule_map=rules)
        n = _upsert_facts(conn, "fact_values_year", folded)
        conn.commit()
    return {"year_rows_upserted": n}


def rollup_all(*, ts_from: str | None = None, ts_to: str | None = None) -> dict:
    """Run full cascade for a time window."""
    out = {}
    out.update(rollup_rop_to_hour(ts_from=ts_from, ts_to=ts_to))
    out.update(rollup_rop_to_day(ts_from=ts_from, ts_to=ts_to))
    out.update(rollup_day_to_week(ts_from=ts_from, ts_to=ts_to))
    out.update(rollup_week_to_month(ts_from=ts_from, ts_to=ts_to))
    out.update(rollup_month_to_year(ts_from=ts_from, ts_to=ts_to))
    return out


def apply_retention() -> dict:
    """Delete old facts per retention policy; purge staging gz."""
    init_schema()
    now = _now()
    cut_15 = (now - timedelta(days=config.FACT_15M_RETENTION_DAYS)).isoformat().replace(
        "+00:00", "Z"
    )
    cut_h = (now - timedelta(days=config.FACT_HOUR_RETENTION_DAYS)).isoformat().replace(
        "+00:00", "Z"
    )
    cut_d = (now - timedelta(days=config.FACT_DAY_RETENTION_DAYS)).isoformat().replace(
        "+00:00", "Z"
    )
    cut_w = (now - timedelta(days=config.FACT_WEEK_RETENTION_DAYS)).isoformat().replace(
        "+00:00", "Z"
    )
    cut_m = (
        now - timedelta(days=31 * config.FACT_MONTH_RETENTION_MONTHS)
    ).isoformat().replace("+00:00", "Z")
    cut_y = (
        now - timedelta(days=366 * config.FACT_YEAR_RETENTION_YEARS)
    ).isoformat().replace("+00:00", "Z")

    deleted = {}
    with connect() as conn:
        for table, cut in (
            ("fact_values_15m", cut_15),
            ("fact_values_hour", cut_h),
            ("fact_values_day", cut_d),
            ("fact_values_week", cut_w),
            ("fact_values_month", cut_m),
            ("fact_values_year", cut_y),
        ):
            t = qident(table)
            cur = execute(conn, f"DELETE FROM {t} WHERE bucket_ts < ?", (cut,))
            deleted[table] = cur.rowcount if cur.rowcount is not None else -1
        conn.commit()

    removed_files = 0
    staging = config.STAGING_DIR
    if staging.exists():
        cutoff = now.timestamp() - config.RAW_RETENTION_HOURS * 3600
        for p in staging.rglob("*"):
            if p.is_file():
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
                        removed_files += 1
                except OSError:
                    pass
    deleted["staging_files"] = removed_files
    return deleted
