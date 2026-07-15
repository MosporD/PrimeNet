#!/usr/bin/env python3
"""Build JSON cache from Nokia performance reference Excel files."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.performance_dictionary.nokia_loader import (
    NOKIA_CACHE_PATH,
    NOKIA_PERF_DIR,
    build_nokia_data_from_excel,
    write_nokia_cache,
)


def main() -> int:
    if not os.path.isdir(NOKIA_PERF_DIR):
        print(f"Missing Nokia Performance directory: {NOKIA_PERF_DIR}")
        return 1

    data = build_nokia_data_from_excel()
    if not data.get("measurement_index"):
        print(f"No Nokia performance Excel files found in: {NOKIA_PERF_DIR}")
        return 1

    path = write_nokia_cache(data)
    meta = data.get("meta") or {}
    print(f"Built {path}")
    print(f"  Sources: {', '.join(meta.get('source') or [])}")
    print(
        f"  Measurements: {meta.get('measurement_count')}  "
        f"Counters: {meta.get('counter_count')}  "
        f"KPIs: {meta.get('kpi_count')}"
    )
    print(f"  Technologies: {', '.join(meta.get('technologies') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
