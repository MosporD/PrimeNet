"""Pilot CLI — measure the whole path end to end on the committed sample file.

    python -m pm_warehouse.pilot init                 # schema + dictionaries
    python -m pm_warehouse.pilot ingest <file...>     # ingest real files
    python -m pm_warehouse.pilot synth --enbs 10 --rops 96
                                                      # synthetic scale-out day
    python -m pm_warehouse.pilot rollup               # h -> d -> w -> m
    python -m pm_warehouse.pilot kpi LTE_5003a --grain day --scope cell
    python -m pm_warehouse.pilot verify               # idempotency proof
    python -m pm_warehouse.pilot stats                # sizes + ledger

The synth command answers "what does a day look like" without a day of real
files: it re-parses the sample once per eNB-ROP with object DNs remapped and
buckets shifted, so parse cost is real, fold cost is real, and the write path
sees exactly the row volume a real day would produce.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from pm_warehouse import db, dictionary, ingest, kpi, rollup, schema
from pm_warehouse.nokia_adapter import Block, iter_blocks

SAMPLE = os.path.join(_REPO, "PM202604260945+030072LNBTS.xml")


def observed_families(path: str) -> dict[str, list[str]]:
    fams: dict[str, list[str]] = {}
    for b in iter_blocks(path, sum_rule=None):
        if b.family not in fams:
            fams[b.family] = list(b.counters)
    return fams


def load_context(sample: str = SAMPLE):
    counters = dictionary.load_nokia_counters("4G")
    fams = schema.build_family_defs(observed_families(sample), counters)
    sum_rule = {
        nid for fam in fams.values() for nid, rule in fam.rules.items()
        if rule in ("SUM",)
    }
    return counters, fams, sum_rule


def cmd_init(args) -> None:
    counters, fams, _ = load_context()
    kpis = dictionary.load_nokia_kpis("4G")
    conn = db.connect()
    t = time.perf_counter()
    schema.apply_schema(conn, fams)
    schema.load_dictionary_rows(conn, counters, kpis, fams)
    conn.close()
    print(f"init: {len(fams)} families x {len(schema.GRAINS)} grains, "
          f"{len(counters):,} dictionary counters, {len(kpis):,} KPI formulas "
          f"in {time.perf_counter()-t:.1f}s")


def cmd_ingest(args) -> None:
    _, fams, sum_rule = load_context()
    conn = db.connect()
    for path in args.files:
        st = ingest.ingest_file(conn, path, fams, sum_rule)
        print(f"{os.path.basename(path)}: {st}")
    conn.close()


def cmd_synth(args) -> None:
    """Synthetic day: N eNBs x M ROPs from the sample, honest write volume."""
    _, fams, sum_rule = load_context()
    conn = db.connect()
    writer = ingest.HourWriter(conn, fams)

    # parse once into a template, then replay with DN/bucket remapping
    template = list(iter_blocks(SAMPLE, sum_rule=sum_rule))
    parse_once = _bench_parse()
    day0 = datetime(2026, 4, 26, tzinfo=timezone.utc)

    t_all = time.perf_counter()
    fold_s = write_s = 0.0
    rows_total = 0
    for enb in range(args.enbs):
        fold = ingest.HourFold(fams)
        t0 = time.perf_counter()
        for rop in range(args.rops):
            shift = day0 + timedelta(seconds=900 * rop)
            for b in template:
                fold.add(Block(
                    b.family,
                    b.base_dn.replace("MRBTS-2619", f"MRBTS-9{enb:04d}")
                             .replace("LNBTS-2619", f"LNBTS-9{enb:04d}"),
                    b.binding_key, shift, b.gran_sec, b.counters, b.values,
                ))
        fold_s += time.perf_counter() - t0
        t1 = time.perf_counter()
        rows_total += writer.write(fold)
        write_s += time.perf_counter() - t1
        print(f"  eNB {enb+1}/{args.enbs}: fold {fold_s:.1f}s cum, "
              f"write {write_s:.1f}s cum, rows {rows_total:,}", flush=True)
    wall = time.perf_counter() - t_all

    files_eq = args.enbs * args.rops
    print(f"\nSYNTH DAY  {args.enbs} eNBs x {args.rops} ROPs "
          f"= {files_eq} file-equivalents")
    print(f"  parse (measured once, real file): {parse_once*1000:6.1f} ms/file "
          f"-> {parse_once*files_eq:6.1f}s for the batch")
    print(f"  fold : {fold_s:7.1f}s  ({fold_s/files_eq*1000:6.1f} ms/file-eq)")
    print(f"  write: {write_s:7.1f}s  ({rows_total/max(write_s,1e-9):,.0f} rows/s merge)")
    print(f"  wall : {wall:7.1f}s   hourly rows written: {rows_total:,}")
    conn.close()


def _bench_parse() -> float:
    _, fams, sum_rule = load_context()
    best = float("inf")
    for _ in range(3):
        t = time.perf_counter()
        n = 0
        for b in iter_blocks(SAMPLE, sum_rule=sum_rule):
            n += 1
        best = min(best, time.perf_counter() - t)
    return best


def cmd_rollup(args) -> None:
    _, fams, _ = load_context()
    conn = db.connect()
    t0 = datetime(2000, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2100, 1, 1, tzinfo=timezone.utc)
    t = time.perf_counter()
    written = rollup.run_rollups(conn, fams, t0, t1)
    print(f"rollup: {written} in {time.perf_counter()-t:.1f}s")
    conn.close()


def cmd_kpi(args) -> None:
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("SELECT name, formula FROM pm.dim_kpi WHERE kpi_id=%s",
                    (args.kpi_id,))
        row = cur.fetchone()
    if not row:
        print(f"unknown KPI {args.kpi_id}"); return
    name, formula = row
    meta = kpi.counter_meta_from_db(conn)
    sql, _ = kpi.compile_kpi(formula, meta, grain=args.grain,
                             object_scope=args.scope)
    t0 = datetime(2000, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2100, 1, 1, tzinfo=timezone.utc)
    t = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, {"t0": t0, "t1": t1})
        rows = cur.fetchall()
    dt = time.perf_counter() - t
    print(f"{args.kpi_id} — {name}\n  formula: {formula[:100]}")
    print(f"  {len(rows)} rows in {dt*1000:.0f} ms  (grain={args.grain}, "
          f"scope={args.scope})")
    for r in rows[: args.limit]:
        okey = (r[0] or "")[-28:]
        val = f"{r[2]:.4f}" if r[2] is not None else "NULL"
        comp = f"{r[3]:.0%}" if r[3] is not None else "?"
        print(f"    {okey:30s} {str(r[1])[:16]}  value={val:>12s}  complete={comp}")
    conn.close()


def cmd_verify(args) -> None:
    """Idempotency: ingesting the same file twice must not change the facts."""
    _, fams, sum_rule = load_context()
    conn = db.connect()

    def snapshot() -> list:
        out = []
        with conn.cursor() as cur:
            for fam in sorted(fams):
                tbl = schema.family_table(fam, "h")
                cur.execute(
                    f"SELECT count(*), coalesce(sum(n_present),0) FROM pm.{tbl}")
                out.append((fam, *cur.fetchone()))
        return out

    st1 = ingest.ingest_file(conn, SAMPLE, fams, sum_rule)
    snap1 = snapshot()
    st2 = ingest.ingest_file(conn, SAMPLE, fams, sum_rule)
    snap2 = snapshot()
    assert st2.get("skipped"), f"second ingest was not skipped: {st2}"
    assert snap1 == snap2, "facts changed on duplicate ingest!"
    print(f"verify: first ingest {st1.get('rows', 0):,} rows; "
          f"duplicate correctly skipped (ledger); facts unchanged. OK")
    conn.close()


def cmd_stats(args) -> None:
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT relname, n_live_tup,
                   pg_size_pretty(pg_total_relation_size('pm.'||relname))
            FROM pg_stat_user_tables WHERE schemaname='pm'
            ORDER BY pg_total_relation_size('pm.'||relname) DESC LIMIT 12
        """)
        print(f"{'table':34s} {'rows':>12s} {'size':>10s}")
        for rel, n, size in cur.fetchall():
            print(f"{rel:34s} {n:12,} {size:>10s}")
        cur.execute("""
            SELECT state, count(*), coalesce(sum(rows_kept),0),
                   coalesce(avg(parse_ms),0)::int, coalesce(avg(write_ms),0)::int
            FROM pm.ingest_ledger GROUP BY state
        """)
        for state, n, kept, p, w in cur.fetchall():
            print(f"ledger[{state}]: files={n} kept_values={kept:,} "
                  f"avg parse={p}ms write={w}ms")
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        print("database total:", cur.fetchone()[0])
    conn.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="pm_warehouse.pilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sp = sub.add_parser("ingest")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(fn=cmd_ingest)
    sp = sub.add_parser("synth")
    sp.add_argument("--enbs", type=int, default=10)
    sp.add_argument("--rops", type=int, default=96)
    sp.set_defaults(fn=cmd_synth)
    sub.add_parser("rollup").set_defaults(fn=cmd_rollup)
    sp = sub.add_parser("kpi")
    sp.add_argument("kpi_id")
    sp.add_argument("--grain", default="day", choices=list(kpi.TIME_GRAINS))
    sp.add_argument("--scope", default="cell", choices=list(kpi.OBJECT_SCOPES))
    sp.add_argument("--limit", type=int, default=8)
    sp.set_defaults(fn=cmd_kpi)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
