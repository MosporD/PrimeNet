#!/usr/bin/env python3
"""Build JSON cache from Nokia Parameter Description.xlsx."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.parameter_dictionary.nokia_loader import (
    NOKIA_CACHE_PATH,
    NOKIA_PARAMS_DIR,
    build_nokia_data_from_excel,
    write_nokia_cache,
)


def main() -> int:
    if not os.path.isdir(NOKIA_PARAMS_DIR):
        print(f"Missing Nokia Parameters directory: {NOKIA_PARAMS_DIR}")
        return 1

    data = build_nokia_data_from_excel()
    if not data.get("mos"):
        print(f"No Nokia Excel files found in: {NOKIA_PARAMS_DIR}")
        return 1

    path = write_nokia_cache(data)
    meta = data.get("meta") or {}
    print(f"Built {path}")
    print(f"  Sources: {meta.get('source')}")
    print(f"  MOs: {meta.get('mo_count')}  Parameters: {meta.get('param_count')}  Rows: {meta.get('row_count')}")
    print(f"  Technologies: {', '.join(meta.get('technologies') or [])}")
    skipped = meta.get("skipped_duplicate_sheets") or []
    if skipped:
        print(f"  Skipped duplicate sheets: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
