"""Refresh Nokia NetAct CM inventory cache (MRBTS / RNC / BSC)."""

from __future__ import annotations

import argparse
import json

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.config import nokia_configured, nokia_defaults
from core.cm_extractor.extraction import build_nokia_client
from core.cm_extractor.nokia_discovery import refresh_nokia_inventory_cache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--scopes',
        default='MRBTS,RNC,BSC',
        help='Comma-separated scope levels to discover (default: MRBTS,RNC,BSC)',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Print full discovery result as JSON',
    )
    args = parser.parse_args()

    if not nokia_configured():
        print('Nokia CM is not configured. Set NOKIA_CM_HOST, NOKIA_CM_USER, NOKIA_CM_PASSWORD in .env.')
        return 1

    scopes = tuple(s.strip().upper() for s in args.scopes.split(',') if s.strip())
    client = build_nokia_client()
    result = refresh_nokia_inventory_cache(client, scopes=scopes)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    scope_counts = {
        level: len(items or [])
        for level, items in (result.get('scopes') or {}).items()
    }
    print(f'Nokia inventory refreshed ({nokia_defaults().get("host") or "NetAct"})')
    for level, count in sorted(scope_counts.items()):
        print(f'  {level}: {count} element(s)')
    print(f'  total NE count: {result.get("ne_count", 0)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
