#!/usr/bin/env python3
"""Build sharded JSON cache from Nokia performance reference Excel files."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.performance_dictionary.nokia_loader import (
    NOKIA_CACHE_DIR,
    NOKIA_CACHE_INDEX,
    NOKIA_CACHE_PATH,
    NOKIA_PERF_DIR,
    build_nokia_data_from_excel,
    write_nokia_cache,
    _load_sharded_cache,
    _read_json,
)


def main() -> int:
    if os.path.isfile(NOKIA_CACHE_PATH):
        print(f"Migrating legacy monolith: {NOKIA_CACHE_PATH}")
        data = _read_json(NOKIA_CACHE_PATH)
    elif os.path.isdir(NOKIA_PERF_DIR):
        print(f"Building from Excel in: {NOKIA_PERF_DIR}")
        data = build_nokia_data_from_excel()
    else:
        print(f"Missing Nokia Performance directory: {NOKIA_PERF_DIR}")
        return 1

    if not data.get("measurement_index"):
        print("No measurements found — nothing to write.")
        return 1

    path = write_nokia_cache(data)
    reloaded = _load_sharded_cache()
    meta = reloaded.get("meta") or {}

    print(f"Wrote sharded cache index: {path}")
    print(f"  Directory: {NOKIA_CACHE_DIR}")
    print(f"  Sources: {', '.join(meta.get('source') or [])}")
    print(
        f"  Measurements: {meta.get('measurement_count')}  "
        f"Counters: {len(reloaded.get('counters') or {})}  "
        f"KPIs: {meta.get('kpi_count')}"
    )
    print(f"  Counter shards: {', '.join(sorted((meta.get('counter_shards') or {}).keys()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
