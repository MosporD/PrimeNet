#!/usr/bin/env python3
"""
Ingest ~1 hour of Nokia NBI ROP data into PM Plus (does NOT enable Excel/ETL pipeline).

Default: newest 4 buckets/stream (4×15min = 1h) with a file cap for local laptops.
Use --full to process every file in those buckets (can be thousands; long run).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from core.pm_plus import config
from core.pm_plus import ledger
from core.pm_plus.ingest import discover_remote_files, process_claimed_row, _pick_host
from core.pm_plus.query import warehouse_stats
from core.pm_plus.schema import init_schema


def main() -> int:
    ap = argparse.ArgumentParser(description="PM Plus ~1 hour local ingest (ETL gate ignored)")
    ap.add_argument("--buckets", type=int, default=4, help="ROP buckets per stream (4 ≈ 1 hour)")
    ap.add_argument(
        "--max-files",
        type=int,
        default=120,
        help="Stop after this many successful ingests (0 = no cap / --full)",
    )
    ap.add_argument("--full", action="store_true", help="No file cap (all files in selected buckets)")
    ap.add_argument("--workers", type=int, default=0, help="Parallel SFTP/ingest workers")
    ap.add_argument("--claim", type=int, default=24, help="Files claimed per batch")
    args = ap.parse_args()

    max_files = 0 if args.full else max(0, args.max_files)
    workers = args.workers or config.DOWNLOAD_WORKERS

    print("[pm-plus-hour] ETL pipeline left alone (this script ignores NCM_ENABLE_ETL).")
    print(
        f"[pm-plus-hour] backend={'postgres' if config.use_postgres() else 'sqlite'} "
        f"host={config.NOKIA_PM_FTP_PRIMARY_HOST} buckets/stream={args.buckets} "
        f"max_files={max_files or 'ALL'} workers={workers}"
    )

    init_schema()
    t0 = time.perf_counter()
    try:
        discovered = discover_remote_files(max_buckets_per_stream=args.buckets)
    except Exception as exc:  # noqa: BLE001
        print(f"[pm-plus-hour] discover failed: {exc}")
        return 1

    print(f"[pm-plus-hour] discovered/upserted ledger rows this scan: {len(discovered)}")
    # Summarize newest buckets seen
    buckets = {}
    for d in discovered:
        key = f"{d['stream']}/{d['bucket']}"
        buckets[key] = buckets.get(key, 0) + 1
    for key, n in sorted(buckets.items())[:20]:
        print(f"  bucket {key}: {n} file(s) in this scan")

    host_cfg = _pick_host()
    ok = fail = 0
    batches = 0
    while True:
        if max_files and ok >= max_files:
            break
        claim_n = args.claim
        if max_files:
            claim_n = min(claim_n, max_files - ok)
        claimed = ledger.claim_next(limit=claim_n)
        if not claimed:
            print("[pm-plus-hour] no more discovered files to claim.")
            break
        batches += 1
        print(f"[pm-plus-hour] batch {batches}: claiming {len(claimed)}…")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(process_claimed_row, row, host_cfg) for row in claimed]
            for fut in as_completed(futs):
                r = fut.result()
                if r.get("ok"):
                    ok += 1
                    if ok % 10 == 0 or ok <= 3:
                        print(
                            f"  ok={ok} samples={r.get('samples_15m')} "
                            f"hour_rows={r.get('hour_rows')} file={Path(str(r.get('path') or '')).name}"
                        )
                else:
                    fail += 1
                    print(f"  FAIL: {r.get('error')}")
        snap = ledger.health_snapshot()
        print(
            f"[pm-plus-hour] progress ok={ok} fail={fail} "
            f"backlog={snap.get('backlog_files')} lag_min={snap.get('lag_minutes')}"
        )

    elapsed = time.perf_counter() - t0
    stats = warehouse_stats()
    print("[pm-plus-hour] done")
    print(f"  elapsed_s={elapsed:.1f} ok={ok} fail={fail}")
    print(f"  warehouse={stats}")
    if max_files and not args.full:
        print(
            f"  note: capped at {max_files} files for local test. "
            "Re-run with --full for every file in the 1h buckets."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
