#!/usr/bin/env python3
"""Build deduplicated repeater sheet (one row per serial, latest Submit_Date)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.network_map.repeater_loader import (  # noqa: E402
    _find_latest_raw_repeater_file,
    write_cleaned_repeater_sheet,
)


def main() -> int:
    source = _find_latest_raw_repeater_file()
    if source is None:
        print("No repeater spreadsheet found under network-map/repeater/")
        return 1

    dest, n_in, n_out = write_cleaned_repeater_sheet(source)
    removed = n_in - n_out
    print(f"Source:  {source} ({n_in:,} rows — service requests)")
    print(f"Output:  {dest} ({n_out:,} rows — one row per Rep_Serial_Num)")
    print(f"Removed: {removed:,} duplicate request rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
