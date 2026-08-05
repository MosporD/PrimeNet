"""RET Management business logic — Huawei RETSUBUNIT and Nokia RETU angle."""

from __future__ import annotations

import re
from typing import Any

from core.cm_extractor.config import huawei_configured, nokia_configured
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.mml_parser import normalize_mml_command, parse_mml_report, repair_mml_rows
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_mass_modify import (
    apply_mass_modifications,
    is_empty_plan_error,
)
from core.cm_extractor.nokia_operations_client import NokiaOperationsError
from core.cm_extractor.nokia_semantics import (
    build_mo_path,
    filter_mo_ids_for_site,
    get_mo_class_catalog,
    query_parameters_individually,
    query_selected_parameters,
    resolve_scope_instance_id,
)
from core.cm_extractor.site_catalog import (
    list_huawei_db_sites,
    list_nokia_inventory_sites,
    merge_huawei_ne_names,
    resolve_huawei_ne_names,
    resolve_nokia_netact_site_id,
)

HUAWEI_MO = 'RETSUBUNIT'
# Runtime RETU_R holds live angles; writes go to config RETU via configDN.
NOKIA_MO_ABBREV_READ = 'RETU_R'
NOKIA_MO_ABBREV_WRITE = 'RETU'
NOKIA_MO_CLASS_READ_FALLBACK = 'com.nokia.srbts.eqmr:RETU_R'
NOKIA_MO_CLASS_WRITE_FALLBACK = 'com.nokia.srbts.eqm:RETU'
# Params verified on NetAct EQMR (antFreqBand / antBeamwidth are not defined).
NOKIA_RETU_PARAMS: tuple[str, ...] = (
    '$instance',
    'angle',
    'minAngle',
    'maxAngle',
    'mechanicalAngle',
    'sectorID',
    'baseStationID',
    'subunitNumber',
    'antModel',
    'antSerial',
    'antBearing',
    'installDate',
    'installerID',
    'operationalState',
    'configDN',
)
NOKIA_DISPLAY_COLUMNS: tuple[str, ...] = (
    'DN',
    '$instance',
    'sectorID',
    'angle',
    'minAngle',
    'maxAngle',
    'mechanicalAngle',
    'baseStationID',
    'antModel',
    'antSerial',
    'antBearing',
    'subunitNumber',
    'installDate',
    'operationalState',
)
# U2020 MOD RETSUBUNIT TILT is in 0.1° steps (40 = 4.0°, 80 = 8.0°). 32767 means unset.
HUAWEI_TILT_UNSET = 32767

# Column order from huawei_param_dict_catalog.json for RETSUBUNIT LST output.
HUAWEI_RET_COLUMNS: tuple[str, ...] = (
    'Device No.',
    'Subunit No.',
    'Connect Port 1 Cabinet No.',
    'Connect Port 1 Subrack No.',
    'Connect Port 1 Slot No.',
    'Connect Port 1 Port No.',
    'Connect Port 2 Cabinet No.',
    'Connect Port 2 Subrack No.',
    'Connect Port 2 Slot No.',
    'Connect Port 2 Port No.',
    'Tilt',
    'Tilt Alarm Error Range',
    'Subunit Name',
    'Online Status',
    'Actual Tilt',
    'Actual Sector ID',
    'RET Configuration Data File Name',
    'Configuration Data File Load Time',
)

HUAWEI_TABLE_COLUMNS: tuple[str, ...] = (
    'Device No.',
    'Subunit No.',
    'Subunit Name',
    'Tilt',
    'Actual Tilt',
    'Online Status',
    'NE',
)

# Common LST RETSUBUNIT widths when U2020 omits optional port columns.
_RET_COLUMN_TEMPLATES: dict[int, tuple[str, ...]] = {
    3: ('Device No.', 'Subunit No.', 'Subunit Name'),
    4: ('Device No.', 'Subunit No.', 'Tilt', 'Online Status'),
    5: ('Device No.', 'Subunit No.', 'Tilt', 'Actual Tilt', 'Online Status'),
    6: ('Device No.', 'Subunit No.', 'Connect Port 1 Cabinet No.', 'Connect Port 1 Subrack No.', 'Tilt', 'Actual Tilt'),
    7: (
        'Device No.',
        'Subunit No.',
        'Connect Port 1 Cabinet No.',
        'Connect Port 1 Subrack No.',
        'Tilt',
        'Actual Tilt',
        'Online Status',
    ),
}

def _format_degrees(deg: float) -> str:
    rounded = round(deg, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f'{rounded:.1f}'


def mml_tilt_to_degrees_display(raw: str) -> str:
    """Human-readable degrees label for an MML tilt value (40 → 4.0°)."""
    text = str(raw or '').strip()
    if not text:
        return ''
    try:
        if '.' in text:
            return _format_degrees(float(text))
        as_int = int(text)
        if as_int == HUAWEI_TILT_UNSET:
            return ''
        return _format_degrees(as_int / 10.0)
    except ValueError:
        return text


def normalize_mml_tilt_input(value: str) -> str:
    """Validate tilt for MOD RETSUBUNIT — pass through U2020 MML integer (0.1° steps)."""
    text = str(value or '').strip()
    if not text:
        raise ValueError('Tilt value is required')
    if '.' in text:
        raise ValueError(
            f'Invalid tilt value {text!r} — use U2020 MML integer units '
            f'(0.1° steps, e.g. 40 for 4.0°, same as manual MOD RETSUBUNIT)'
        )
    try:
        mml = int(text)
    except ValueError as exc:
        raise ValueError(
            f'Invalid tilt value {text!r} — use U2020 MML integer units '
            f'(0.1° steps, e.g. 40 for 4.0°)'
        ) from exc
    if mml == HUAWEI_TILT_UNSET:
        raise ValueError('Tilt 32767 is reserved (unset) on U2020')
    if mml < -900 or mml > 900:
        raise ValueError(
            f'Tilt {mml} is out of range (-900 to +900, i.e. -90° to +90° in 0.1° steps)'
        )
    return str(mml)


_HUAWEI_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    'Device No.': ('Device No.', 'DeviceNo', 'DEVICENO', 'Device No'),
    'Subunit No.': ('Subunit No.', 'SubunitNo', 'SUBUNITNO', 'Subunit No'),
    'Subunit Name': ('Subunit Name', 'SubunitName', 'SUBUNITNAME'),
    'Tilt': ('Tilt', 'TILT'),
    'Actual Tilt': ('Actual Tilt', 'ActualTilt', 'RtmTilt', 'RTMTILT'),
    'Online Status': ('Online Status', 'OnlineStatus', 'Status', 'STATUS'),
}


def _normalize_key(key: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (key or '').lower())


def _is_huawei_tilt_field(key: str) -> bool:
    norm = _normalize_key(str(key))
    if not norm.startswith('tilt'):
        return False
    if 'actual' in norm:
        return False
    if 'alarm' in norm or 'error' in norm or 'range' in norm:
        return False
    return True


def _is_huawei_actual_tilt_field(key: str) -> bool:
    norm = _normalize_key(str(key))
    return 'actual' in norm and 'tilt' in norm


def _alias_lookup(row: dict[str, Any], canonical: str) -> str:
    for key in _HUAWEI_FIELD_ALIASES.get(canonical, (canonical,)):
        if key in row and str(row.get(key) or '').strip() != '':
            return str(row[key]).strip()
    norm_target = _normalize_key(canonical)
    for key, value in row.items():
        if _normalize_key(str(key)) == norm_target:
            return str(value or '').strip()
    if canonical == 'Device No.':
        for key, value in row.items():
            if _normalize_key(str(key)).startswith('deviceno'):
                text = str(value or '').strip()
                if text:
                    return text
    if canonical == 'Subunit No.':
        for key, value in row.items():
            if _normalize_key(str(key)).startswith('subunitno'):
                text = str(value or '').strip()
                if text:
                    return text
    if canonical == 'Tilt':
        for key, value in row.items():
            if _is_huawei_tilt_field(key):
                text = str(value or '').strip()
                if text:
                    return text
    if canonical == 'Actual Tilt':
        for key, value in row.items():
            if _is_huawei_actual_tilt_field(key):
                text = str(value or '').strip()
                if text:
                    return text
    return ''


def _ret_column_template(value_count: int) -> tuple[str, ...]:
    if value_count in _RET_COLUMN_TEMPLATES:
        return _RET_COLUMN_TEMPLATES[value_count]
    if value_count <= len(HUAWEI_RET_COLUMNS):
        return HUAWEI_RET_COLUMNS[:value_count]
    return HUAWEI_RET_COLUMNS


def _split_ret_header_line(line: str) -> list[str]:
    stripped = (line or '').strip()
    if not stripped:
        return []
    if '\t' in stripped:
        parts = [part.strip() for part in stripped.split('\t') if part.strip()]
        if parts:
            return parts
    parts = re.split(r'\s{2,}', stripped)
    parts = [part.strip() for part in parts if part.strip()]
    if len(parts) >= 3 and _looks_like_ret_header(parts):
        return parts

    # U2020 sometimes prints headers with single spaces between multi-word labels.
    remaining = stripped
    headers: list[str] = []
    candidates = sorted(HUAWEI_RET_COLUMNS, key=len, reverse=True)
    while remaining:
        matched = ''
        for cand in candidates:
            if remaining.lower().startswith(cand.lower()):
                matched = cand
                remaining = remaining[len(cand):].strip()
                break
        if not matched:
            break
        headers.append(matched)
    return headers


def _split_ret_line(line: str) -> list[str]:
    stripped = (line or '').strip()
    if not stripped:
        return []
    if '\t' in stripped:
        return [part.strip() for part in stripped.split('\t') if part.strip()]
    parts = re.split(r'\s{2,}', stripped)
    if len(parts) >= 2:
        return [part.strip() for part in parts if part.strip()]
    return [part.strip() for part in stripped.split() if part.strip()]


def _looks_like_ret_header(parts: list[str]) -> bool:
    norms = {_normalize_key(str(part)) for part in parts}
    if 'deviceno' in norms and (
        'subunitno' in norms or 'tilt' in norms or 'subunitname' in norms or 'actualtilt' in norms
    ):
        return True
    joined = f" {' '.join(parts).lower()} "
    return 'device no' in joined and (
        'subunit no' in joined or ' tilt' in joined or ' actual tilt' in joined
    )


def _looks_like_ret_data(parts: list[str]) -> bool:
    if len(parts) < 3:
        return False
    return parts[0].replace('.', '', 1).isdigit()


def parse_ret_mml_report(report: str) -> list[dict[str, Any]]:
    """Parse RETSUBUNIT LST reports, including single-space U2020 tables."""
    if not report:
        return []

    lines = [
        ln.strip()
        for ln in report.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        if ln.strip() and not ln.strip().startswith(('+++', '---', '%%'))
    ]
    header: list[str] = []
    header_idx = -1
    for idx, line in enumerate(lines):
        header_parts = _split_ret_header_line(line)
        if header_parts and _looks_like_ret_header(header_parts):
            header = header_parts
            header_idx = idx
            break
        # Greedy header tokenization can return valid RET columns without passing the
        # double-space header check — accept Device No. + Subunit No. explicitly.
        if header_parts and not header:
            norms = {_normalize_key(str(part)) for part in header_parts}
            if 'deviceno' in norms and 'subunitno' in norms:
                header = header_parts
                header_idx = idx
                break

    rows: list[dict[str, Any]] = []
    if header:
        width = len(header)
        for line in lines[header_idx + 1:]:
            lower = line.lower()
            if lower.startswith('(number of results') or lower.startswith('retecode') or lower.startswith('retcode'):
                break
            parts = _split_ret_line(line)
            if not parts or not _looks_like_ret_data(parts):
                continue
            row = {
                header[col_idx]: parts[col_idx] if col_idx < len(parts) else ''
                for col_idx in range(width)
            }
            rows.append(row)
        if rows:
            return rows

    # Fallback to generic parser output with positional remap.
    return parse_mml_report(report)


def _uses_generic_columns(row: dict[str, Any]) -> bool:
    keys = [str(k) for k in row if str(k) not in ('NE', '_mml_warnings', 'report')]
    if any(str(k).startswith('Column ') for k in keys):
        return True
    norms = {_normalize_key(str(k)) for k in keys}
    if 'localcellid' in norms and 'deviceno' not in norms:
        return True
    return False


def _generic_value_list(row: dict[str, Any]) -> list[str]:
    """Extract ordered cell values from misparsed Local cell ID / Column N rows."""
    lcid_key = next(
        (k for k in row if _normalize_key(str(k)) in ('localcellid', 'deviceno')),
        None,
    )
    values: list[str] = []
    if lcid_key is not None:
        values.append(str(row.get(lcid_key) or '').strip())

    col_idx = 1
    while f'Column {col_idx}' in row:
        values.append(str(row.get(f'Column {col_idx}') or '').strip())
        col_idx += 1

    if not values:
        numeric_keys = sorted(
            (str(k) for k in row if str(k).startswith('Column ')),
            key=lambda name: int(name.split()[-1]) if name.split()[-1].isdigit() else 0,
        )
        for key in numeric_keys:
            values.append(str(row.get(key) or '').strip())

    if not values:
        ordered = [
            str(row.get(k) or '').strip()
            for k in row
            if str(k) not in ('NE', '_mml_warnings', 'report')
        ]
        values = [v for v in ordered if v]
    return values


def _remap_generic_ret_row(row: dict[str, Any]) -> dict[str, Any]:
    if not _uses_generic_columns(row):
        return row
    values = _generic_value_list(row)
    if not values:
        return row
    headers = _ret_column_template(len(values))
    out: dict[str, Any] = {}
    for idx, col_name in enumerate(headers):
        if idx < len(values):
            out[col_name] = values[idx]
    for key in ('NE', '_mml_warnings'):
        if key in row:
            out[key] = row[key]
    return out


def normalize_huawei_ret_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonicalize RETSUBUNIT column names and drop junk rows."""
    normalized: list[dict[str, Any]] = []
    skip_meta = frozenset({'NE', '_mml_warnings', 'report'})
    for row in rows or []:
        row = _remap_generic_ret_row(dict(row))
        if _is_header_echo_row(row):
            continue
        device = _alias_lookup(row, 'Device No.')
        subunit = _alias_lookup(row, 'Subunit No.')
        if not device and not subunit:
            if not _alias_lookup(row, 'Tilt') and not _alias_lookup(row, 'Actual Tilt'):
                continue
        out: dict[str, Any] = {}
        for canonical in HUAWEI_TABLE_COLUMNS:
            if canonical == 'NE':
                continue
            val = _alias_lookup(row, canonical)
            if val:
                out[canonical] = val
        # Keep wide LST fields (connect ports, alarm range, etc.) for display.
        for key, value in row.items():
            if key in skip_meta or key in out:
                continue
            text = str(value or '').strip()
            if text:
                out[key] = text
        for key in ('NE', '_mml_warnings'):
            if key in row:
                out[key] = row[key]
        if out:
            # Canonical Tilt/Actual Tilt for API consumers and MOD path.
            tilt_val = _alias_lookup(out, 'Tilt')
            if tilt_val and not out.get('Tilt'):
                out['Tilt'] = tilt_val
            actual_val = _alias_lookup(out, 'Actual Tilt')
            if actual_val and not out.get('Actual Tilt'):
                out['Actual Tilt'] = actual_val
            normalized.append(out)
    return normalized


def _is_header_echo_row(row: dict[str, Any]) -> bool:
    """Drop rows where the parser treated the title line as data."""
    device = _alias_lookup(row, 'Device No.')
    subunit = _alias_lookup(row, 'Subunit No.')
    tilt = _alias_lookup(row, 'Tilt')
    if device.lower() in ('device no.', 'device no', 'deviceno'):
        return True
    if subunit.lower() in ('subunit no.', 'subunit no', 'subunitno'):
        return True
    if tilt.lower() == 'tilt':
        return True
    return False


def _row_key(row: dict[str, Any]) -> str:
    lookup = {_normalize_key(k): str(v or '').strip() for k, v in row.items()}
    device = lookup.get('deviceno', '')
    subunit = lookup.get('subunitno', '')
    if device or subunit:
        return f'{device}:{subunit}'
    return str(row.get('NE') or row.get('ne') or '')


def list_network_elements(
    vendor: str,
    *,
    query: str = '',
    limit: int = 500,
) -> list[dict[str, Any]]:
    vendor = (vendor or 'nokia').strip().lower()
    if vendor == 'nokia':
        items, _source = list_nokia_inventory_sites(query, scope_level='MRBTS', limit=limit)
        return items
    if vendor == 'huawei':
        return list_huawei_db_sites(query, scope_level='ENODEB', limit=limit)
    raise ValueError('Vendor must be nokia or huawei')


def _rows_to_records(headers: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(headers, row)) for row in rows]


def _parse_ret_report_rows(report: str, fallback_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not report:
        return list(fallback_rows or [])
    parsed = parse_ret_mml_report(report)
    if not parsed:
        parsed = parse_mml_report(report)
    if not parsed:
        parsed = list(fallback_rows or [])
    return parsed


def _collect_ret_rows_from_reports(
    reports: list[dict[str, Any]],
    *,
    ne_name: str,
) -> list[dict[str, Any]]:
    raw_rows: list[dict[str, Any]] = []
    for item in reports:
        ne = str(item.get('ne_name') or ne_name).strip()
        report = str(item.get('report') or '')
        fallback = list(item.get('rows') or []) if isinstance(item.get('rows'), list) else []
        for row in _parse_ret_report_rows(report, fallback):
            item_row = dict(row)
            item_row['NE'] = ne
            raw_rows.append(item_row)
    return raw_rows


def _normalize_ret_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not raw_rows:
        return []
    if all(not _uses_generic_columns(row) for row in raw_rows):
        return normalize_huawei_ret_rows(raw_rows)
    return normalize_huawei_ret_rows(repair_mml_rows(raw_rows))


def _ret_row_key(row: dict[str, Any]) -> str:
    return f"{_alias_lookup(row, 'Device No.')}:{_alias_lookup(row, 'Subunit No.')}"


def _merge_lst_dsp_rows(
    lst_rows: list[dict[str, Any]],
    dsp_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """LST supplies configured Tilt; DSP supplies runtime Actual Tilt."""
    dsp_by_key = {
        _ret_row_key(row): row
        for row in dsp_rows
        if _ret_row_key(row) != ':'
    }
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in lst_rows:
        key = _ret_row_key(row)
        seen.add(key)
        out = dict(row)
        dsp_row = dsp_by_key.get(key, {})
        actual = _alias_lookup(dsp_row, 'Actual Tilt')
        if actual:
            out['Actual Tilt'] = actual
        for field in ('Tilt', 'Subunit Name', 'Online Status'):
            if not _alias_lookup(out, field):
                dsp_val = _alias_lookup(dsp_row, field)
                if dsp_val:
                    out[field] = dsp_val
        merged.append(out)
    for key, dsp_row in dsp_by_key.items():
        if key in seen:
            continue
        merged.append(dict(dsp_row))
    return merged


def _run_ret_mml(
    client: HuaweiCmClient,
    ne_name: str,
    verb: str,
    *,
    device_no: str = '',
    subunit_no: str = '',
) -> tuple[list[dict[str, Any]], list[str]]:
    if device_no and subunit_no:
        command = normalize_mml_command(
            f'{verb} {HUAWEI_MO}: DEVICENO={device_no},SUBUNITNO={subunit_no}'
        )
    else:
        command = normalize_mml_command(f'{verb} {HUAWEI_MO}')
    return client.run_mml_reports(command, [ne_name])


def _summarize_ret_mml_warnings(errors: list[str], *, label: str) -> list[str]:
    """Collapse repeated per-subunit MML failures into one readable warning."""
    if not errors:
        return []
    if len(errors) == 1:
        return [f'{label}: {errors[0]}']
    bodies: list[str] = []
    for err in errors:
        text = str(err or '').strip()
        if ': ' in text:
            text = text.split(': ', 1)[1]
        bodies.append(text)
    unique = list(dict.fromkeys(bodies))
    detail = unique[0] if len(unique) == 1 else '; '.join(unique[:2])
    sample = str(errors[0] or '').strip()
    return [
        f'{label} failed for {len(errors)} subunit(s): {detail}'
        + (f' (example: {sample})' if sample and sample not in detail else '')
    ]


def _row_has_tilt_values(row: dict[str, Any]) -> bool:
    return bool(_alias_lookup(row, 'Tilt') or _alias_lookup(row, 'Actual Tilt'))


def _fetch_scoped_ret_rows_for_subunits(
    client: HuaweiCmClient,
    ne_name: str,
    lst_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Enrich abbreviated bulk LST rows with per-subunit detail.

    Prefer scoped LST (read right) over DSP (often denied or unsupported on NBI accounts).
    """
    detail_rows: list[dict[str, Any]] = []
    lst_errors: list[str] = []
    dsp_errors: list[str] = []
    seen_keys: set[str] = set()

    for row in lst_rows:
        key = _ret_row_key(row)
        if not key or key == ':' or key in seen_keys:
            continue
        seen_keys.add(key)
        device = _alias_lookup(row, 'Device No.')
        subunit = _alias_lookup(row, 'Subunit No.')
        if not device or not subunit:
            continue

        lst_reports, batch_lst_errors = _run_ret_mml(
            client,
            ne_name,
            'LST',
            device_no=device,
            subunit_no=subunit,
        )
        lst_errors.extend(batch_lst_errors)
        scoped_lst = _normalize_ret_rows(
            _collect_ret_rows_from_reports(lst_reports, ne_name=ne_name)
        )
        if scoped_lst:
            detail_rows = _merge_lst_dsp_rows(detail_rows, scoped_lst)

        probe_rows = _merge_lst_dsp_rows([row], scoped_lst)
        probe = probe_rows[0] if probe_rows else row
        if _row_has_tilt_values(probe):
            continue

        dsp_reports, batch_dsp_errors = _run_ret_mml(
            client,
            ne_name,
            'DSP',
            device_no=device,
            subunit_no=subunit,
        )
        dsp_errors.extend(batch_dsp_errors)
        scoped_dsp = _normalize_ret_rows(
            _collect_ret_rows_from_reports(dsp_reports, ne_name=ne_name)
        )
        if scoped_dsp:
            detail_rows = _merge_lst_dsp_rows(detail_rows, scoped_dsp)

    warnings: list[str] = []
    warnings.extend(_summarize_ret_mml_warnings(lst_errors, label='LST RETSUBUNIT (scoped)'))
    warnings.extend(_summarize_ret_mml_warnings(dsp_errors, label='DSP RETSUBUNIT'))
    return detail_rows, warnings


def _row_populated_field_count(row: dict[str, Any]) -> int:
    skip = frozenset({'NE', '_mml_warnings', 'report'})
    return sum(
        1 for key, value in row.items()
        if key not in skip and str(value or '').strip() != ''
    )


def _rows_missing_tilt_values(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    return not any(_row_has_tilt_values(row) for row in rows)


def _rows_needing_scoped_enrichment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Only re-query U2020 for abbreviated bulk rows (device/subunit/name only).

    Wide bulk LST (many columns) is kept as-is — per-subunit calls often fail
    and can trigger U2020 rate limits after a successful first load.
    """
    needing: list[dict[str, Any]] = []
    for row in rows:
        if _row_has_tilt_values(row):
            continue
        if _row_populated_field_count(row) > 4:
            continue
        needing.append(row)
    return needing


def fetch_huawei_rets(
    client: HuaweiCmClient,
    *,
    ne_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    ne_name = (ne_name or '').strip()
    if not ne_name:
        raise ValueError('Network element name is required')

    warnings: list[str] = []
    lst_reports, lst_errors = _run_ret_mml(client, ne_name, 'LST')
    lst_rows = _normalize_ret_rows(_collect_ret_rows_from_reports(lst_reports, ne_name=ne_name))
    warnings.extend(lst_errors)

    detail_rows: list[dict[str, Any]] = []
    rows_needing = _rows_needing_scoped_enrichment(lst_rows)
    if rows_needing:
        detail_rows, detail_warnings = _fetch_scoped_ret_rows_for_subunits(
            client,
            ne_name,
            rows_needing,
        )
        warnings.extend(detail_warnings)

    rows = _merge_lst_dsp_rows(lst_rows, detail_rows)
    if rows and _rows_missing_tilt_values(rows):
        if rows_needing:
            warnings.append(
                'Tilt values are unavailable from U2020 for abbreviated RET rows. '
                'Scoped LST/DSP did not return tilt — check NBI MML rights or whether '
                'tilt is unset (32767) on the NE.'
            )
        elif _row_populated_field_count(rows[0]) > 4:
            warnings.append(
                'Bulk LST returned wide RETSUBUNIT data but no Tilt/Actual Tilt fields '
                'were present in the U2020 response.'
            )
    if not rows and lst_errors:
        raise HuaweiCmError('; '.join(lst_errors[:5]))
    return rows, warnings


def build_huawei_mod_command(
    *,
    device_no: str,
    subunit_no: str,
    tilt: str,
    extra: dict[str, str] | None = None,
) -> str:
    device_no = str(device_no or '').strip()
    subunit_no = str(subunit_no or '').strip()
    if not device_no or not subunit_no:
        raise ValueError('Device No. and Subunit No. are required')
    mml_tilt = normalize_mml_tilt_input(tilt)

    parts = [f'DEVICENO={device_no}', f'SUBUNITNO={subunit_no}', f'TILT={mml_tilt}']
    for key, value in (extra or {}).items():
        token = re.sub(r'[^A-Za-z0-9]+', '', str(key or '')).upper()
        val = str(value or '').strip()
        if token and val:
            parts.append(f'{token}={val}')
    # U2020 expects comma-separated parameters without spaces (matches manual MML form).
    return normalize_mml_command(f'MOD {HUAWEI_MO}:{",".join(parts)}')


def _huawei_mml_vendor_request(command: str, ne_name: str) -> dict[str, Any]:
    return {
        'method': 'POST',
        'path': '/api/rest/mmlManagement/v1/command',
        'body': {
            'command': command,
            'neNames': [ne_name],
        },
    }


def apply_huawei_ret_update(
    client: HuaweiCmClient,
    *,
    ne_name: str,
    device_no: str,
    subunit_no: str,
    tilt: str,
) -> dict[str, Any]:
    ne_name = (ne_name or '').strip()
    if not ne_name:
        raise ValueError('Network element name is required')

    device_no = str(device_no or '').strip()
    subunit_no = str(subunit_no or '').strip()
    if not device_no or not subunit_no:
        raise ValueError('Device No. and Subunit No. are required')

    command = build_huawei_mod_command(
        device_no=device_no,
        subunit_no=subunit_no,
        tilt=tilt,
    )
    vendor_request = _huawei_mml_vendor_request(command, ne_name)
    reports, errors = client.run_mml_reports(command, [ne_name])
    if errors:
        detail = '; '.join(errors[:3])
        report_excerpt = ''
        for item in reports:
            report = str(item.get('report') or '').strip()
            if report:
                report_excerpt = report[:800]
                break
        message = f'{detail} Command: {command}'
        if 'tilt' in detail.lower() and 'invalid' in detail.lower():
            mml_match = re.search(r'TILT=(\d+)', command, re.IGNORECASE)
            if mml_match:
                mml_val = mml_match.group(1)
                deg_label = mml_tilt_to_degrees_display(mml_val)
                message += (
                    f' U2020 TILT uses 0.1° steps (e.g. 40 = 4.0°); '
                    f'TILT={mml_val} means {deg_label}°.'
                )
        if report_excerpt and report_excerpt.lower() not in detail.lower():
            message = f'{message} Report: {report_excerpt}'
        raise HuaweiCmError(
            message,
            payload={
                'vendor_request': vendor_request,
                'errors': errors[:5],
                'report': report_excerpt,
            },
        )
    return {
        'command': command,
        'vendor_request': vendor_request,
        'rows': reports,
        'errors': errors,
    }


def resolve_huawei_ne(site_id: str, ne_name: str | None = None) -> str:
    site_id = str(site_id or '').strip()
    explicit = str(ne_name or '').strip()
    if explicit:
        return explicit
    if not site_id:
        raise ValueError('site_id or ne_name is required')
    resolved = resolve_huawei_ne_names([site_id])
    names = merge_huawei_ne_names(site_ids=[site_id], ne_names=resolved)
    if not names:
        raise ValueError(f'Could not resolve U2020 NE name for site {site_id}')
    return names[0]


def _score_mo_adaptation(adaptation: str, *, prefer_runtime: bool) -> int:
    """Score NetAct adaptations for RETU read (eqmr) or write (eqm)."""
    adapt = (adaptation or '').strip().lower()
    score = 0
    if prefer_runtime:
        if 'eqmr' in adapt:
            score += 20
        elif adapt.endswith('.eqm') or adapt == 'eqm':
            score -= 5
    else:
        if 'eqmr' in adapt:
            score -= 20
        elif adapt.endswith('.eqm') or adapt == 'eqm':
            score += 10
        elif 'eqm' in adapt:
            score += 5
    if 'srbts' in adapt:
        score += 5
    if 'nokia' in adapt or adapt.startswith('com.'):
        score += 1
    if adapt.startswith('com.nokia.srbts.hw'):
        score -= 50
    return score


def _resolve_mo_class_by_abbreviation(
    client: NokiaCmClient | None,
    abbreviation: str,
    *,
    prefer_runtime: bool,
    fallback: str,
) -> str:
    abbrev = (abbreviation or '').strip().upper()
    if client is not None:
        try:
            catalog = get_mo_class_catalog(client, ran_only=True, scope_level='MRBTS')
        except Exception:
            catalog = []
        matches = [
            item for item in catalog
            if (item.get('abbreviation') or '').strip().upper() == abbrev
        ]
        if matches:
            matches.sort(
                key=lambda item: (
                    _score_mo_adaptation(
                        str(item.get('adaptation') or ''),
                        prefer_runtime=prefer_runtime,
                    ),
                    str(item.get('version') or ''),
                ),
                reverse=True,
            )
            return matches[0]['id']
    return fallback


def resolve_nokia_retu_read_mo_class(client: NokiaCmClient | None = None) -> str:
    """Runtime RETU_R — live angle / device status."""
    return _resolve_mo_class_by_abbreviation(
        client,
        NOKIA_MO_ABBREV_READ,
        prefer_runtime=True,
        fallback=NOKIA_MO_CLASS_READ_FALLBACK,
    )


def resolve_nokia_retu_write_mo_class(client: NokiaCmClient | None = None) -> str:
    """Config RETU — Provision_Mass_Modification target for angle."""
    return _resolve_mo_class_by_abbreviation(
        client,
        NOKIA_MO_ABBREV_WRITE,
        prefer_runtime=False,
        fallback=NOKIA_MO_CLASS_WRITE_FALLBACK,
    )


# Backward-compatible name used by routes during migration.
resolve_nokia_retu_mo_class = resolve_nokia_retu_write_mo_class
NOKIA_MO_CLASS_FALLBACK = NOKIA_MO_CLASS_WRITE_FALLBACK


def config_retu_dist_name(row: dict[str, Any]) -> str:
    """Map a runtime RETU_R row to the config RETU distinguished name for writes."""
    config_dn = str(row.get('configDN') or row.get('configDn') or '').strip()
    if config_dn:
        if config_dn.startswith('PLMN-'):
            return config_dn
        return f'PLMN-PLMN/{config_dn.lstrip("/")}'

    runtime_dn = str(row.get('runtime_DN') or row.get('DN') or row.get('dn') or '').strip()
    if not runtime_dn:
        return ''
    return (
        runtime_dn
        .replace('/EQM_R-', '/EQM-')
        .replace('/APEQM_R-', '/APEQM-')
        .replace('/ALD_R-', '/ALD-')
        .replace('/RETU_R-', '/RETU-')
    )


def _retu_write_dist_name_candidates(item: dict[str, Any]) -> list[str]:
    """Candidate config RETU DNs for Provision_Mass_Modification."""
    candidates: list[str] = []

    def add(dn: str) -> None:
        token = str(dn or '').strip()
        if token and token not in candidates:
            candidates.append(token)

    add(config_retu_dist_name(item))
    dist = str(item.get('dist_name') or item.get('DN') or item.get('dn') or '').strip()
    if '/RETU_R-' in dist:
        add(config_retu_dist_name({'DN': dist, 'runtime_DN': dist}))
    elif dist:
        add(dist)

    site_id = str(item.get('site_id') or '').strip()
    seed = candidates[0] if candidates else ''
    if site_id and seed and '/MRBTS-' in seed:
        for netact_id in _mrbts_query_element_ids(site_id):
            rewritten = re.sub(r'/MRBTS-[^/]+/', f'/MRBTS-{netact_id}/', seed, count=1)
            add(rewritten)

    return candidates


def _mrbts_query_element_ids(site_id: str) -> list[str]:
    """Candidate NetAct MRBTS instance ids to scope RETU_R queries."""
    ids: list[str] = []
    for candidate in (
        site_id,
        resolve_scope_instance_id(site_id, 'MRBTS'),
        resolve_nokia_netact_site_id(site_id),
    ):
        token = str(candidate or '').strip()
        if token and token not in ids:
            ids.append(token)
    return ids


def _filter_retu_records_for_site(
    records: list[dict[str, Any]],
    site_id: str,
) -> list[dict[str, Any]]:
    """Keep only RETU rows whose DN belongs to the selected MRBTS."""
    if not site_id or not records:
        return records
    kept: list[dict[str, Any]] = []
    for record in records:
        dn = str(
            record.get('runtime_DN')
            or record.get('DN')
            or record.get('dn')
            or ''
        ).strip()
        if dn and filter_mo_ids_for_site([dn], site_id, scope_level='MRBTS'):
            kept.append(record)
    return kept


def fetch_nokia_retu_angles(
    client: NokiaCmClient,
    *,
    site_id: str,
    conf_id: int = 1,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """
    Read live RET angles from RETU_R.

    Returns (rows, warnings, write_mo_class). Each row's DN is the config RETU
    DN used for angle writes; runtime_DN keeps the RETU_R path.
    """
    site_id = str(site_id or '').strip()
    if not site_id:
        raise ValueError('site_id is required')

    read_mo_class = resolve_nokia_retu_read_mo_class(client)
    write_mo_class = resolve_nokia_retu_write_mo_class(client)
    if ':' not in read_mo_class:
        raise ValueError(f'Invalid RETU_R MO class id: {read_mo_class}')
    adaptation, abbreviation = read_mo_class.split(':', 1)
    params = list(NOKIA_RETU_PARAMS)
    warnings: list[str] = []

    def _query(mo_path: str) -> tuple[list[str], list[list[Any]]]:
        try:
            return query_selected_parameters(
                client,
                mo_path,
                params,
                adaptation=adaptation,
                abbreviation=abbreviation,
                conf_id=conf_id,
                site_id=site_id,
                scope_level='MRBTS',
            )
        except NokiaCmError:
            # Avoid surfacing noisy batch errors; retry per-parameter quietly.
            return query_parameters_individually(
                client,
                mo_path,
                params,
                conf_id=conf_id,
                site_id=site_id,
                scope_level='MRBTS',
                include_all_columns=True,
            )

    headers: list[str] = []
    rows: list[list[Any]] = []
    for element_id in _mrbts_query_element_ids(site_id):
        mo_path = build_mo_path(
            adaptation,
            abbreviation,
            scope_level='MRBTS',
            element_id=element_id,
        )
        headers, rows = _query(mo_path)
        if rows:
            break

    if not rows:
        mo_path = build_mo_path(adaptation, abbreviation, scope_level='MRBTS', element_id=None)
        headers, rows = _query(mo_path)

    records = _rows_to_records(headers, rows)
    raw_count = len(records)
    for record in records:
        runtime_dn = str(record.get('DN') or record.get('dn') or '').strip()
        if runtime_dn:
            record['runtime_DN'] = runtime_dn
        write_dn = config_retu_dist_name(record)
        if write_dn:
            record['DN'] = write_dn

    records = _filter_retu_records_for_site(records, site_id)
    if raw_count and len(records) != raw_count:
        warnings.append(
            f'Scoped RETU_R query returned network-wide data; kept {len(records)} '
            f'row(s) for site {site_id}.'
        )

    if not records:
        warnings.append(
            f'No {abbreviation} instances returned for this site ({read_mo_class}).'
        )
    return records, warnings, write_mo_class


# Backward-compatible alias during LNCEL → RETU migration.
fetch_nokia_lncel_angles = fetch_nokia_retu_angles


def apply_nokia_angle_changes(
    username: str,
    updates: list[dict[str, Any]],
    *,
    wait: bool = True,
    mo_class: str | None = None,
    operations_client=None,
) -> dict[str, Any]:
    del username  # PrimeNet username is tracked in activity_log; CM auth uses vendor creds
    if not updates:
        raise ValueError('No angle updates provided')

    class_id = (mo_class or '').strip() or NOKIA_MO_CLASS_WRITE_FALLBACK
    all_operations: list[dict[str, Any]] = []

    for item in updates:
        angle = str(item.get('angle') if item.get('angle') is not None else '').strip()
        if not angle:
            raise ValueError('Each update requires angle')
        item_class = str(item.get('mo_class') or item.get('mo_class_id') or class_id).strip()
        if item_class.endswith(':RETU_R') or item_class.upper().endswith('RETU_R'):
            item_class = NOKIA_MO_CLASS_WRITE_FALLBACK

        dn_candidates = _retu_write_dist_name_candidates(item)
        if not dn_candidates:
            raise ValueError('Each update requires dist_name (DN) or configDN')

        # Runtime RETU_R angle often differs from planned RETU — omit old_value for Mass Provision.
        mass_item = {
            'parameter': 'angle',
            'new_value': angle,
            'mo_class': item_class,
        }

        last_error: Exception | None = None
        applied = False
        for dist_name in dn_candidates:
            try:
                result = apply_mass_modifications(
                    [{**mass_item, 'dist_name': dist_name}],
                    wait=wait,
                    mo_class=class_id,
                    client=operations_client,
                )
                all_operations.extend(result.get('operations') or [])
                applied = True
                break
            except Exception as exc:
                last_error = exc
                if is_empty_plan_error(str(exc)) and dist_name != dn_candidates[-1]:
                    continue
                raise
        if not applied and last_error:
            raise last_error

    return {
        'operation_name': 'Provision_Mass_Modification',
        'change_count': len(all_operations),
        'operations': all_operations,
    }


def vendor_status() -> dict[str, bool]:
    return {
        'nokia_configured': nokia_configured(),
        'huawei_configured': huawei_configured(),
    }
