"""Rebuild the Huawei U2020 parameter dictionary cache JSON."""

from __future__ import annotations

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.huawei_param_dict import load_catalog


def main() -> int:
    catalog = load_catalog(rebuild=True)
    meta = catalog.get('meta') or {}
    print('Huawei parameter dictionary rebuilt.')
    print(f'  MO types: {meta.get("mo_count", len(catalog.get("mos") or {}))}')
    print(f'  Parameters: {meta.get("param_count", "n/a")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
