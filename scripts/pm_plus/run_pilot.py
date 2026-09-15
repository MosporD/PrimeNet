#!/usr/bin/env python3
"""Phase 0 pilot: parse one PM file (local sample or path) into the warehouse."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from core.pm_plus.ingest import ingest_local_file
from core.pm_plus.query import warehouse_stats
from core.pm_plus.schema import init_schema


def _ensure_gz(xml_path: Path) -> Path:
    if xml_path.suffix.lower() == ".gz":
        return xml_path
    out = Path(tempfile.gettempdir()) / f"{xml_path.stem}.xml.gz"
    with open(xml_path, "rb") as src, gzip.open(out, "wb") as dst:
        dst.write(src.read())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="PM Plus single-file ingest pilot")
    ap.add_argument(
        "--file",
        default="",
        help="Path to .xml or .gz (default: bundled sample)",
    )
    ap.add_argument("--json", action="store_true", help="Print JSON only")
    args = ap.parse_args()

    init_schema()
    if args.file:
        path = Path(args.file)
    else:
        sample = ROOT / "core" / "pm_plus" / "testdata" / "sample_meas.xml"
        path = _ensure_gz(sample)

    result = ingest_local_file(
        path,
        host="pilot",
        stream="sample",
        bucket="phase0",
        relpath=path.name,
    )
    result["warehouse"] = warehouse_stats()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PM Plus Phase-0 pilot")
        print(f"  file:     {result['path']}")
        print(f"  backend:  {result['backend']}")
        print(f"  samples:  {result['samples_15m']}")
        print(f"  hour rows:{result['hour_rows']}")
        print(f"  objects:  {result['objects']}")
        print(f"  counters: {result['counters']}")
        print(f"  families: {', '.join(result['families'])}")
        print(
            f"  timing:   parse={result['parse_seconds']}s "
            f"write={result['write_seconds']}s total={result['total_seconds']}s"
        )
        print(f"  warehouse:{result['warehouse']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
