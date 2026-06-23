"""Run a CM extraction from a JSON payload file (Open API or Huawei MML)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.extraction import run_extraction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path, help='JSON payload (same shape as /api/cm-extractor/extract)')
    parser.add_argument('-o', '--output', type=Path, required=True, help='Output .xlsx path')
    args = parser.parse_args()

    payload = json.loads(args.payload.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        summary = run_extraction(payload, str(args.output))
    except Exception as exc:
        print(f'Extraction failed: {exc}')
        return 1

    print(f'Wrote {args.output}')
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
