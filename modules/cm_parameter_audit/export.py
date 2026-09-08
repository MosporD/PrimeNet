"""Excel export for CM Parameter Audit live scan results."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def _safe_filename_part(value: str, *, fallback: str = 'param') -> str:
    cleaned = re.sub(r'[^\w\-]+', '_', (value or '').strip())
    return cleaned.strip('_') or fallback


def build_audit_workbook(payload: dict[str, Any]) -> tuple[io.BytesIO, str]:
    """Build a multi-sheet workbook from a live audit payload."""
    if str(payload.get('audit_mode') or 'parameter') == 'mo':
        return _build_mo_workbook(payload)
    return _build_parameter_workbook(payload)


def _payload_warnings(payload: dict[str, Any]) -> list:
    items = list(payload.get('warnings') or [])
    items.extend(payload.get('admin_notes') or [])
    return items


def _style_header(ws, headers: list[str], hdr_fill, hdr_font) -> None:
    for col, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal='center')


def _build_parameter_workbook(payload: dict[str, Any]) -> tuple[io.BytesIO, str]:
    """Build a multi-sheet workbook from a live audit payload."""
    summary = payload.get('summary') or {}
    ne_scope = payload.get('ne_scope') or {}
    distribution = (
        summary.get('value_distribution_all')
        or summary.get('value_distribution')
        or []
    )
    rows = payload.get('rows') or []
    warnings = _payload_warnings(payload)

    vendor = str(payload.get('vendor') or '')
    mo_class = str(payload.get('mo_class') or '')
    parameter = str(payload.get('parameter') or '')
    scope_level = str(payload.get('scope_level') or '')
    query_column = str(payload.get('query_column') or parameter)
    query_mode = str(payload.get('query_mode') or '')
    area = str(ne_scope.get('area') or payload.get('area') or 'all')

    wb = Workbook()
    hdr_fill = PatternFill(start_color='1F6FEB', end_color='1F6FEB', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)

    # --- Summary ---
    ws_summary = wb.active
    ws_summary.title = 'Summary'
    ws_summary.column_dimensions['A'].width = 28
    ws_summary.column_dimensions['B'].width = 48
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    meta_rows = [
        ('Generated (UTC)', generated),
        ('Vendor', vendor),
        ('Scope', scope_level),
        ('MO Class', mo_class),
        ('Parameter', parameter),
        ('Query Column', query_column),
        ('Query Mode', query_mode),
        ('Area', area),
        ('NEs Queried', ne_scope.get('queried', '')),
        ('NEs Available', ne_scope.get('available', '')),
        ('Scope Truncated', 'Yes' if ne_scope.get('truncated') else 'No'),
        ('Objects', summary.get('object_count', 0)),
        ('Distinct NEs', summary.get('ne_count', 0)),
        ('Distinct Values', summary.get('distinct_values', 0)),
        ('Dominant Value', summary.get('most_common_value', '')),
        ('Dominant Count', summary.get('most_common_count', 0)),
        ('Inconsistent Count', summary.get('inconsistent_count', 0)),
        ('Inconsistency %', summary.get('inconsistency_pct', 0)),
        ('Consistency Status', summary.get('status', '')),
    ]
    ws_summary['A1'] = 'Field'
    ws_summary['B1'] = 'Value'
    _style_header(ws_summary, ['Field', 'Value'], hdr_fill, hdr_font)
    for idx, (field, value) in enumerate(meta_rows, start=2):
        ws_summary.cell(row=idx, column=1, value=field)
        ws_summary.cell(row=idx, column=2, value=value)

    if payload.get('note'):
        note_row = len(meta_rows) + 3
        ws_summary.cell(row=note_row, column=1, value='Note')
        ws_summary.cell(row=note_row, column=2, value=str(payload.get('note')))

    # --- Value distribution ---
    ws_dist = wb.create_sheet('Value Distribution')
    dist_headers = ['Value', 'Count', 'Percent']
    _style_header(ws_dist, dist_headers, hdr_fill, hdr_font)
    ws_dist.column_dimensions['A'].width = 36
    ws_dist.column_dimensions['B'].width = 12
    ws_dist.column_dimensions['C'].width = 12
    for item in distribution:
        ws_dist.append([
            item.get('value', ''),
            item.get('count', 0),
            item.get('percent', 0),
        ])
    if not distribution:
        ws_dist.append(['(no data)', 0, 0])

    # --- Network status ---
    ws_rows = wb.create_sheet('Network Status')
    row_headers = ['NE', 'Site ID', 'Area', 'Cell / Object', 'DN', 'Value', 'Status']
    _style_header(ws_rows, row_headers, hdr_fill, hdr_font)
    ws_rows.column_dimensions['A'].width = 34
    ws_rows.column_dimensions['B'].width = 14
    ws_rows.column_dimensions['C'].width = 16
    ws_rows.column_dimensions['D'].width = 28
    ws_rows.column_dimensions['E'].width = 42
    ws_rows.column_dimensions['F'].width = 18
    ws_rows.column_dimensions['G'].width = 12
    for row in rows:
        object_label = row.get('cell_name') or row.get('object') or row.get('dn') or ''
        status = 'Dominant' if row.get('matches_dominant') else 'Variant'
        ws_rows.append([
            row.get('ne', ''),
            row.get('site_id', ''),
            row.get('area', ''),
            object_label,
            row.get('dn', ''),
            row.get('value', ''),
            status,
        ])
    if not rows:
        ws_rows.append(['(no data)', '', '', '', '', '', ''])

    # --- Warnings ---
    if warnings or payload.get('note'):
        ws_warn = wb.create_sheet('Warnings')
        _style_header(ws_warn, ['Message'], hdr_fill, hdr_font)
        ws_warn.column_dimensions['A'].width = 100
        if payload.get('note'):
            ws_warn.append([str(payload.get('note'))])
        for message in warnings:
            ws_warn.append([str(message)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = (
        f'CM_Parameter_Audit_{_safe_filename_part(vendor)}_'
        f'{_safe_filename_part(mo_class)}_{_safe_filename_part(parameter)}_{stamp}.xlsx'
    )
    return buf, filename


def _build_mo_workbook(payload: dict[str, Any]) -> tuple[io.BytesIO, str]:
    summary = payload.get('summary') or {}
    ne_scope = payload.get('ne_scope') or {}
    param_summaries = payload.get('parameter_summaries') or []
    objects = payload.get('object_matrix') or []
    warnings = _payload_warnings(payload)

    vendor = str(payload.get('vendor') or '')
    mo_class = str(payload.get('mo_class') or '')
    scope_level = str(payload.get('scope_level') or '')
    query_mode = str(payload.get('query_mode') or '')
    area = str(ne_scope.get('area') or payload.get('area') or 'all')
    parameters = [str(item.get('parameter') or '') for item in param_summaries if item.get('parameter')]

    wb = Workbook()
    hdr_fill = PatternFill(start_color='1F6FEB', end_color='1F6FEB', fill_type='solid')
    hdr_font = Font(color='FFFFFF', bold=True)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    ws_summary = wb.active
    ws_summary.title = 'Summary'
    ws_summary.column_dimensions['A'].width = 32
    ws_summary.column_dimensions['B'].width = 48
    meta_rows = [
        ('Generated (UTC)', generated),
        ('Vendor', vendor),
        ('Scope', scope_level),
        ('MO Class', mo_class),
        ('Audit Mode', 'Entire MO'),
        ('Query Mode', query_mode),
        ('Area', area),
        ('NEs Queried', ne_scope.get('queried', '')),
        ('NEs Available', ne_scope.get('available', '')),
        ('Scope Truncated', 'Yes' if ne_scope.get('truncated') else 'No'),
        ('Objects', summary.get('object_count', 0)),
        ('Distinct NEs', summary.get('ne_count', 0)),
        ('Parameters', summary.get('parameter_count', len(parameters))),
        ('Inconsistent Parameters', summary.get('inconsistent_parameter_count', 0)),
        ('Empty Parameters', summary.get('empty_parameter_count', 0)),
        ('Inconsistency %', summary.get('inconsistency_pct', 0)),
        ('Consistency Status', summary.get('status', '')),
    ]
    _style_header(ws_summary, ['Field', 'Value'], hdr_fill, hdr_font)
    for idx, (field, value) in enumerate(meta_rows, start=2):
        ws_summary.cell(row=idx, column=1, value=field)
        ws_summary.cell(row=idx, column=2, value=value)
    if payload.get('note'):
        note_row = len(meta_rows) + 3
        ws_summary.cell(row=note_row, column=1, value='Note')
        ws_summary.cell(row=note_row, column=2, value=str(payload.get('note')))

    ws_params = wb.create_sheet('Parameter Overview')
    param_headers = [
        'Parameter', 'Distinct Values', 'Dominant Value', 'Dominant Count',
        'Inconsistent Count', 'Inconsistency %', 'Status',
    ]
    _style_header(ws_params, param_headers, hdr_fill, hdr_font)
    ws_params.column_dimensions['A'].width = 28
    ws_params.column_dimensions['B'].width = 16
    ws_params.column_dimensions['C'].width = 22
    ws_params.column_dimensions['D'].width = 16
    ws_params.column_dimensions['E'].width = 18
    ws_params.column_dimensions['F'].width = 16
    ws_params.column_dimensions['G'].width = 12
    for item in param_summaries:
        ws_params.append([
            item.get('parameter', ''),
            item.get('distinct_values', 0),
            item.get('most_common_value', ''),
            item.get('most_common_count', 0),
            item.get('inconsistent_count', 0),
            item.get('inconsistency_pct', 0),
            item.get('status', ''),
        ])
    if not param_summaries:
        ws_params.append(['(no data)', 0, '', 0, 0, 0, ''])

    ws_dist = wb.create_sheet('Value Distribution')
    _style_header(ws_dist, ['Parameter', 'Value', 'Count', 'Percent'], hdr_fill, hdr_font)
    ws_dist.column_dimensions['A'].width = 28
    ws_dist.column_dimensions['B'].width = 36
    ws_dist.column_dimensions['C'].width = 12
    ws_dist.column_dimensions['D'].width = 12
    dist_rows = 0
    for item in param_summaries:
        param = item.get('parameter', '')
        entries = item.get('value_distribution_all') or item.get('value_distribution') or []
        for entry in entries:
            ws_dist.append([
                param,
                entry.get('value', ''),
                entry.get('count', 0),
                entry.get('percent', 0),
            ])
            dist_rows += 1
    if not dist_rows:
        ws_dist.append(['(no data)', '', 0, 0])

    ws_rows = wb.create_sheet('Network Status')
    row_headers = ['NE', 'Site ID', 'Area', 'Cell / Object', 'DN', *parameters]
    _style_header(ws_rows, row_headers, hdr_fill, hdr_font)
    ws_rows.column_dimensions['A'].width = 34
    ws_rows.column_dimensions['B'].width = 14
    ws_rows.column_dimensions['C'].width = 16
    ws_rows.column_dimensions['D'].width = 28
    ws_rows.column_dimensions['E'].width = 42
    for idx in range(6, len(row_headers) + 1):
        ws_rows.column_dimensions[ws_rows.cell(row=1, column=idx).column_letter].width = 16
    ws_rows.freeze_panes = 'F2'
    for obj in objects:
        object_label = obj.get('cell_name') or obj.get('object') or obj.get('dn') or ''
        values = obj.get('values') or {}
        ws_rows.append([
            obj.get('ne', ''),
            obj.get('site_id', ''),
            obj.get('area', ''),
            object_label,
            obj.get('dn', ''),
            *[values.get(param, '') for param in parameters],
        ])
    if not objects:
        ws_rows.append(['(no data)', '', '', '', '', *([''] * len(parameters))])

    if warnings or payload.get('note'):
        ws_warn = wb.create_sheet('Warnings')
        _style_header(ws_warn, ['Message'], hdr_fill, hdr_font)
        ws_warn.column_dimensions['A'].width = 100
        if payload.get('note'):
            ws_warn.append([str(payload.get('note'))])
        for message in warnings:
            ws_warn.append([str(message)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = (
        f'CM_Parameter_Audit_{_safe_filename_part(vendor)}_'
        f'{_safe_filename_part(mo_class)}_fullMO_{stamp}.xlsx'
    )
    return buf, filename
