"""Probe NetAct Import_Export for one MRBTS + LNHOIF (read-only actualExport)."""

from __future__ import annotations

import sys

sys.path.insert(0, '.')

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.config import build_nokia_operations_client, nokia_export_ssh_settings
from core.cm_extractor.extraction import build_nokia_client
from core.cm_extractor.nokia_bulk_export import run_controller_bulk_export

SITE_ID = '1201'
SELECTIONS = [{
    'mo_class_id': 'NOKLTE:LNHOIF',
    'version': 'xL25R2_2503_121',
    'export_mode': 'full',
    'parameters': [],
}]


def main() -> int:
    ssh = nokia_export_ssh_settings()
    print('SFTP configured:', ssh.get('configured'), 'host:', ssh.get('host'))
    if not ssh.get('configured'):
        print('SFTP not configured — cannot complete bulk probe.')
        return 1

    cm = build_nokia_client()
    ops = build_nokia_operations_client()
    print(f'Probing Import_Export for MRBTS-{SITE_ID}, class *:LNHOIF …')
    try:
        result = run_controller_bulk_export(
            cm,
            ops,
            scope_level='MRBTS',
            site_ids=[SITE_ID],
            selections=SELECTIONS,
            operation_timeout_sec=900,
        )
    except Exception as exc:
        print('PROBE FAILED:', exc)
        return 1

    print('PROBE OK')
    print('  operation_id:', result.get('operation_id'))
    print('  export_dns:', result.get('export_dns'))
    print('  object_count:', result.get('object_count'))
    print('  row_count:', result.get('row_count'))
    print('  sheets:', result.get('sheet_names'))
    print('  excel:', result.get('excel_path'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
