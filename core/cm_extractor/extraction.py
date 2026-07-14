"""
Vendor-agnostic CM extraction runner.

Shared by the interactive ``/api/cm-extractor/extract`` route and the background
scheduler so both produce identical Excel output from the same selection payload.

A *payload* is the same JSON the browser posts to the extract endpoint (minus any
live connection credentials):

    Nokia : {vendor:'nokia', conf_id, scope_level, site_ids:[...], selections:[...]}
    Huawei: {vendor:'huawei', scope_level, site_ids:[...]|ne_names:[...], selections:[...]}
            (or a single CUSTOM command via {command:'LST CELL'})
"""

from __future__ import annotations

from typing import Any

from core.cm_extractor.config import huawei_defaults, nokia_configured, nokia_defaults
from core.cm_extractor.excel_writer import write_huawei_sheets_excel
from core.cm_extractor.huawei_client import HuaweiCmClient
from core.cm_extractor.huawei_semantics import export_huawei_selection_to_excel
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_semantics import export_nokia_selection_to_excel
from core.cm_extractor.site_catalog import merge_huawei_ne_names, resolve_huawei_ne_names


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(',') if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def build_nokia_client() -> NokiaCmClient:
    if not nokia_configured():
        raise NokiaCmError(
            'Nokia NetAct CM is not configured. Set NOKIA_CM_HOST, NOKIA_CM_USER, '
            'and NOKIA_CM_PASSWORD in .env.'
        )
    cfg = nokia_defaults()
    return NokiaCmClient(
        host=cfg['host'],
        username=cfg['username'],
        password=cfg['password'],
        base_url=cfg.get('base_url') or '',
        use_https=cfg['use_https'],
        verify_ssl=cfg['verify_ssl'],
        timeout=cfg.get('timeout', 180),
        mo_batch_size=cfg.get('mo_batch_size', 150),
        batch_delay_sec=cfg.get('batch_delay_sec', 0.4),
        max_retries=cfg.get('max_retries', 8),
        retry_base_delay_sec=cfg.get('retry_base_delay_sec', 2.0),
    )


def build_huawei_client(conn: dict[str, Any] | None = None) -> HuaweiCmClient:
    cfg = huawei_defaults()
    conn = conn or {}
    port = conn.get('port', cfg['port'])
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = cfg['port']
    return HuaweiCmClient(
        host=conn.get('host') or cfg['host'],
        username=conn.get('username') or cfg['username'],
        password=conn.get('password') or cfg['password'],
        port=port,
        use_https=bool(conn.get('use_https', cfg['use_https'])),
        verify_ssl=bool(conn.get('verify_ssl', cfg['verify_ssl'])),
        api_style=conn.get('api_style') or cfg.get('api_style', 'wireless'),
        client_ip=conn.get('client_ip') or cfg.get('client_ip', ''),
        script_base_url=conn.get('script_base_url') or cfg.get('script_base_url', ''),
    )


def _resolve_huawei_targets(payload: dict[str, Any]) -> tuple[list[str], list[dict], list[dict[str, str]]]:
    site_ids = _as_str_list(payload.get('site_ids'))
    ne_names = _as_str_list(payload.get('ne_names'))
    scope_level = (payload.get('scope_level') or 'ENODEB').strip().upper()
    skipped: list[dict[str, str]] = []

    if not ne_names and site_ids:
        ne_names, unresolved, _alternates, skipped = resolve_huawei_ne_names(site_ids, scope_level=scope_level)
    else:
        ne_names, unresolved, _alternates, skipped = merge_huawei_ne_names(
            site_ids,
            ne_names,
            scope_level=scope_level,
        )

    if unresolved:
        preview = ', '.join(unresolved[:8])
        suffix = '…' if len(unresolved) > 8 else ''
        raise ValueError(
            f'Could not map site id(s) to U2020 NE name: {preview}{suffix}. '
            'Ensure metadata site_name is the OSS meName (e.g. 2222-UL_Site_Name_IBS_M), '
            'or pick NEs from the list after it loads (not paste-only).',
        )
    if not ne_names and not skipped:
        raise ValueError('Select at least one network element')

    selections = payload.get('selections') or []
    if not selections:
        command = (payload.get('command') or '').strip()
        if command:
            selections = [{'mo_id': 'CUSTOM', 'command': command, 'export_all': True}]
        else:
            raise ValueError('Select at least one MO object type and its parameters')
    return ne_names, selections, skipped


def run_extraction(payload: dict[str, Any], output_path: str,
                   *, huawei_conn: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a CM extraction described by ``payload`` and write the workbook to ``output_path``.

    Returns ``{vendor, row_count, sheet_names, summary}``.
    """
    vendor = (payload.get('vendor') or '').lower()

    if vendor == 'nokia':
        conf_id = int(payload.get('conf_id') or 1)
        scope_level = (payload.get('scope_level') or 'MRBTS').strip().upper()
        site_ids = _as_str_list(payload.get('site_ids'))
        selections = payload.get('selections') or []
        if not site_ids:
            raise ValueError('Select at least one site id for the chosen scope')
        if not selections:
            raise ValueError('Select at least one managed object class and its parameters')
        client = build_nokia_client()
        row_count, sheet_names, summary, _extraction_mode = export_nokia_selection_to_excel(
            client,
            output_path,
            selections=selections,
            site_ids=site_ids,
            scope_level=scope_level,
            conf_id=conf_id,
        )
        return {'vendor': vendor, 'row_count': row_count, 'sheet_names': sheet_names, 'summary': summary}

    if vendor == 'huawei':
        ne_names, selections, skipped = _resolve_huawei_targets(payload)
        client = build_huawei_client(huawei_conn)

        if len(selections) == 1 and selections[0].get('mo_id') == 'CUSTOM':
            command = (selections[0].get('command') or payload.get('command') or '').strip()
            if not command:
                raise ValueError('MML command is required')
            client.clear_skipped_mml_nes()
            for row in skipped:
                client._record_skipped_mml_nes([row['NE name']], reason=row['Reason'])
            rows = client.run_mml_chunked(command, ne_names) if ne_names else []
            mml_errors = client.consume_mml_errors()
            skipped_nes = client.consume_skipped_mml_nes()
            if not rows and mml_errors and not skipped_nes:
                raise HuaweiCmError('; '.join(mml_errors[:5]))
            sheets: dict[str, list[dict[str, Any]]] = {'MML_Result': rows}
            sheet_names = ['MML_Result']
            warnings = [f'MML: {err}' for err in mml_errors]
            if skipped_nes:
                sheets['Skipped_NEs'] = skipped_nes
                sheet_names.append('Skipped_NEs')
                preview = ', '.join(row['NE name'] for row in skipped_nes[:8])
                suffix = '…' if len(skipped_nes) > 8 else ''
                warnings.append(
                    f'Skipped {len(skipped_nes)} NE(s) not found in U2020 (name mismatch): {preview}{suffix}. '
                    'See Skipped_NEs sheet.',
                )
            write_huawei_sheets_excel(output_path, sheets)
            return {
                'vendor': vendor,
                'row_count': len(rows),
                'sheet_names': sheet_names,
                'summary': f'Huawei MML custom command on {len(ne_names)} NE(s), {len(rows)} row(s).',
                'warnings': warnings,
            }

        row_count, sheet_names, summary, warnings = export_huawei_selection_to_excel(
            client,
            output_path,
            ne_names=ne_names,
            selections=selections,
            pre_skipped_nes=skipped,
        )
        return {
            'vendor': vendor,
            'row_count': row_count,
            'sheet_names': sheet_names,
            'summary': summary,
            'warnings': warnings,
        }

    raise ValueError(f'Unknown vendor: {vendor}')
