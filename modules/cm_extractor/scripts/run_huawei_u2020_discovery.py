"""Run U2020 NE + MO discovery and write a JSON report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.config import huawei_defaults
from core.cm_extractor.huawei_client import HuaweiCmClient
from core.cm_extractor.huawei_discovery import refresh_discovery_cache
from core.cm_extractor.site_catalog import resolve_huawei_ne_names

DEFAULT_OUT = Path('reports/huawei_u2020_discovery.json')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '-o', '--output',
        type=Path,
        default=DEFAULT_OUT,
        help=f'Output JSON path (default: {DEFAULT_OUT})',
    )
    parser.add_argument(
        '--no-mo-probe',
        action='store_true',
        help='Skip MO command probing on sample NEs',
    )
    args = parser.parse_args()

    cfg = huawei_defaults()
    client = HuaweiCmClient(
        host=cfg['host'],
        username=cfg['username'],
        password=cfg['password'],
        port=cfg['port'],
        verify_ssl=cfg['verify_ssl'],
        api_style=cfg.get('api_style', 'wireless'),
    )
    result = refresh_discovery_cache(
        client,
        include_history=False,
        discover_mos=not args.no_mo_probe,
    )
    resolved, unresolved, _alternates, _skipped = resolve_huawei_ne_names(['1005', '1006'])
    payload = {
        'ne_count': result['ne_count'],
        'site_id_count': result['site_id_count'],
        'sample_ne': result.get('sample_ne'),
        'sample_nes': [row['ne_name'] for row in result['nes'][:25]],
        'mo_columns': result.get('mo_columns') or {},
        'site_resolution': {
            '1005': {'resolved': resolved[0] if resolved else None, 'unresolved': '1005' in unresolved},
            '1006': {
                'resolved': resolved[1] if len(resolved) > 1 else (resolved[0] if resolved else None),
            },
        },
        'nes': result['nes'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f'Wrote {args.output} — {result["ne_count"]} NEs, MO types probed on {result.get("sample_ne")}')
    print('1005/1006 resolve:', payload['site_resolution'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
