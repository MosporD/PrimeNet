#!/usr/bin/env python3
"""Continuous Nokia NBI ingest worker (separate from Gunicorn)."""

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
from core.pm_plus.ingest import run_ingest_cycle
from core.pm_plus.schema import init_schema


def main() -> int:
    ap = argparse.ArgumentParser(description="PM Plus continuous ingest worker")
    ap.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    ap.add_argument("--buckets", type=int, default=2, help="Newest buckets per stream")
    ap.add_argument("--interval", type=int, default=0, help="Override poll interval seconds")
    ap.add_argument(
        "--ignore-etl-gate",
        action="store_true",
        help="Run even when NCM_ENABLE_ETL=0 (PM Plus only; does not start Excel ETL)",
    )
    args = ap.parse_args()

    if not args.ignore_etl_gate:
        from core.etl_gate import require_etl_enabled

        if not require_etl_enabled():
            print(
                "[pm-plus] tip: use --ignore-etl-gate for a local PM Plus pull "
                "while leaving Excel ETL offline",
                file=sys.stderr,
            )
            return 0

    init_schema()
    print(
        f"[pm-plus] backend={'postgres' if config.use_postgres() else 'sqlite'} "
        f"workers={config.DOWNLOAD_WORKERS} hosts={config.NOKIA_PM_FTP_PRIMARY_HOST}/"
        f"{config.NOKIA_PM_FTP_BACKUP_HOST}"
    )
    interval = args.interval or config.POLL_INTERVAL_SEC
    while True:
        try:
            summary = run_ingest_cycle(max_buckets_per_stream=args.buckets)
            print(
                f"[pm-plus] discovered={summary['discovered']} claimed={summary['claimed']} "
                f"ok={summary['ok']} failed={summary['failed']} "
                f"lag_min={summary['lag'].get('lag_minutes')} "
                f"backlog={summary['lag'].get('backlog_files')}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[pm-plus] cycle error: {exc}")
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
