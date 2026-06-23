#!/usr/bin/env python3
"""
Dry-run inspection for Huawei Performance.zip-style archives (no PM database writes).

Shows: ZIP members, which .csv/.txt/.tsv/.dat paths are selected, per-file read headers,
and whether _prepare_pm_df_like_nokia succeeds.

Usage (from project root):

  python scripts/debug_huawei_pm_zip.py path/to/Performance.zip

Verbose stderr lines (openpyxl / CSV stages, etc.):

  set HUAWEI_PM_DEBUG=1
  python scripts/debug_huawei_pm_zip.py path/to/Performance.zip
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    zip_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(zip_path):
        print('Not a file:', zip_path, file=sys.stderr)
        return 1

    from modules.sync.pm_processor import debug_huawei_pm_zip

    report = debug_huawei_pm_zip(zip_path)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
