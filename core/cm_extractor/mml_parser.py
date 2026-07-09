"""
Parse Huawei MML NE response reports into tabular rows.

Handles horizontal list tables (header row + data rows) and simple key=value blocks.
"""

from __future__ import annotations

import re
from typing import Any

_SKIP_LINE_RE = re.compile(
    r'^\s*(?:'
    r'RETCODE\s*='
    r'|\(\s*Number of results\b'
    r'|Display static parameters'
    r'|---+\s*END'
    r'|\+\+\+'
    r'|%+%'
    r'|O&M\b'
    r')',
    re.IGNORECASE,
)

_CELL_HEADER_MARKERS = (
    'local cell id',
    'cell name',
    'physical cell id',
    'csg indicator',
    'nr cell id',
    'enodeb function name',
)

_RET_HEADER_MARKERS = (
    'device no',
    'subunit no',
    'tilt',
    'actual tilt',
    'online status',
)


def _split_columns(line: str) -> list[str]:
    stripped = line.strip()
    if '\t' in stripped:
        parts = [p.strip() for p in stripped.split('\t') if p.strip()]
        if len(parts) >= 2:
            return parts
    parts = re.split(r'\s{2,}', stripped)
    return [p.strip() for p in parts if p.strip()]


def _normalize_key(key: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (key or '').lower())


def _is_known_field_name(text: str) -> bool:
    norm = _normalize_key(text)
    if not norm:
        return False
    for marker in _CELL_HEADER_MARKERS:
        if _normalize_key(marker) == norm:
            return True
    return False


def _is_numeric_cell_id(text: str) -> bool:
    value = str(text or '').strip()
    return bool(value) and value.replace('.', '', 1).isdigit()


def _is_status_key(key: str) -> bool:
    norm = _normalize_key(key)
    if norm in ('retcode', 'retecode'):
        return True
    if 'operationsucceed' in norm:
        return True
    if 'numberofresults' in norm:
        return True
    if 'progressreport' in norm:
        return True
    return False


def _is_status_text(text: str) -> bool:
    lower = (text or '').strip().lower()
    if not lower:
        return False
    if lower.startswith('retcode') and '= 0' in lower:
        return True
    if 'operation succeed' in lower and 'retcode' in lower:
        return True
    if lower.startswith('(number of results'):
        return True
    return False


def _is_status_header(cols: list[str]) -> bool:
    joined = ' '.join(str(col) for col in cols).lower()
    if 'retcode' in joined and ('operation succeed' in joined or joined.strip().endswith('0')):
        return True
    if joined.startswith('(number of results'):
        return True
    return any(_is_status_key(col) or _is_status_text(col) for col in cols)


def _is_mml_status_row(row: dict[str, Any]) -> bool:
    if not row:
        return True
    keys = [str(key) for key in row]
    if all(_is_status_key(key) or _is_status_text(key) for key in keys):
        return True
    joined = ' '.join(f'{key} {value}' for key, value in row.items()).lower()
    if 'retcode' in joined and 'operation succeed' in joined and len(keys) <= 4:
        return True
    if all(
        'retcode' in key.lower() or 'operation succeed' in key.lower()
        for key in keys
    ):
        return True
    return False


def _filter_mml_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not _is_mml_status_row(row)]


def is_status_only_mml_report(report: str) -> bool:
    """True when a report contains only MML status/footer lines, not MO data."""
    lines = [ln.strip() for ln in report.replace('\r\n', '\n').split('\n') if ln.strip()]
    if not lines:
        return True
    for line in lines:
        if _SKIP_LINE_RE.match(line) or _is_status_text(line):
            continue
        if line.startswith('---') or line.startswith('+++'):
            continue
        if line.startswith('(') and 'results' in line.lower():
            continue
        return False
    return True


def _is_likely_column_header_line(parts: list[str]) -> bool:
    """Wide row whose cells are MO field names (not a data row)."""
    if len(parts) < 3:
        return False
    if any(str(part).strip() == '=' for part in parts):
        return False
    if _is_numeric_cell_id(parts[0]):
        return False
    if _is_likely_horizontal_data_row(parts):
        return False
    joined = ' '.join(parts).lower()
    hits = sum(1 for marker in _CELL_HEADER_MARKERS if marker in joined)
    if hits >= 2:
        return True
    ret_hits = sum(1 for marker in _RET_HEADER_MARKERS if marker in joined)
    if ret_hits >= 2:
        return True
    if (
        'local cell id' not in joined
        and 'cell name' not in joined
        and 'nr cell id' not in joined
        and ret_hits < 2
    ):
        return False
    text_hits = sum(
        1 for part in parts
        if re.search(r'[a-zA-Z]{4,}', part)
        and not _is_numeric_cell_id(part)
        and ' ' in part.strip()
    )
    return text_hits >= 2


def _is_likely_horizontal_data_row(parts: list[str]) -> bool:
    """Wide row starting with a numeric local cell id (horizontal data, not header)."""
    if len(parts) < 3:
        return False
    if not _is_numeric_cell_id(parts[0]):
        return False
    numeric_or_enum = sum(
        1 for part in parts[1:]
        if _is_numeric_cell_id(part) or part.replace('.', '', 1).isdigit()
    )
    return numeric_or_enum >= max(1, int((len(parts) - 1) * 0.5))


def _strip_column_header_lines(lines: list[str]) -> list[str]:
    """Drop wide title rows that precede vertical ``Parameter  Value`` blocks."""
    stripped_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            stripped_lines.append(line)
            continue
        parts = _split_columns(stripped)
        if len(parts) >= 3 and _is_likely_column_header_line(parts):
            continue
        stripped_lines.append(line)
    return stripped_lines


_PARAM_NAME_HINTS = (
    'threshold', 'indicator', 'offset', 'period', 'mode', 'timer', 'strategy',
    'configuration', 'bandwidth', 'earfcn', 'physical', 'frequency', 'mobility',
    'load balancing', 'admin state', 'active state', 'prefix length', 'sharing',
    'compression', 'assignment', 'emission', 'preamble', 'radius', 'label',
    'transfer', 'evaluate', 'selection', 'optimization', 'steering', 'vendor',
    'experience', 'spectral', 'video', 'punishment', 'offload', 'prb',
)

_CELL_BLOCK_START_KEYS = frozenset({
    _normalize_key('Local Cell ID'),
    _normalize_key('Local cell ID'),
    _normalize_key('Nr Cell ID'),
    _normalize_key('Device No.'),
    _normalize_key('Device No'),
})


def _looks_like_mml_parameter_name(text: str) -> bool:
    """True when text looks like an MML field label, not a cell/data value."""
    s = str(text or '').strip()
    if not s or _is_numeric_cell_id(s):
        return False
    lower = s.lower()
    if re.search(r':(?:on|off)\b', lower) or 'mode:' in lower:
        return False
    if '&' in s and ':' in s:
        return False
    if _is_known_field_name(s):
        return True
    if re.search(r'\([^)]+\)', lower):
        return True
    if any(hint in lower for hint in _PARAM_NAME_HINTS):
        return True
    words = [w for w in re.split(r'\s+', s) if w]
    if len(words) >= 2 and sum(1 for w in words if w[:1].isupper()) >= 2:
        return True
    return False


def _is_garbage_row_key(key: str) -> bool:
    key_str = str(key or '').strip()
    if not key_str or key_str == '=':
        return True
    return _is_mashed_cell_row_key(key_str)


def _row_has_parameter_values(row: dict[str, Any]) -> bool:
    """Detect horizontal mis-parse rows where values are other parameter names."""
    lcid_key = next((key for key in row if _normalize_key(str(key)) == 'localcellid'), None)
    if lcid_key is None:
        non_meta = [str(k) for k in row if str(k) not in ('NE', '_mml_warnings', 'report')]
        if non_meta and all(_looks_like_mml_parameter_name(str(k)) for k in non_meta):
            vals = [str(row.get(k) or '').strip() for k in non_meta]
            if sum(1 for v in vals if _looks_like_mml_parameter_name(v)) >= max(1, len(vals) // 2):
                return True
        return False
    val_str = str(row.get(lcid_key) or '').strip()
    if val_str and _looks_like_mml_parameter_name(val_str) and not _is_numeric_cell_id(val_str):
        return True
    cell_name_key = next((key for key in row if _normalize_key(str(key)) == 'cellname'), None)
    if cell_name_key is not None:
        cn_val = str(row.get(cell_name_key) or '').strip()
        if cn_val and _looks_like_mml_parameter_name(cn_val):
            return True
    return False


def _is_vertical_pair_line(parts: list[str]) -> bool:
    if len(parts) != 2:
        return False
    if _normalize_key(parts[0]) in _CELL_BLOCK_START_KEYS:
        return True
    return _looks_like_mml_parameter_name(parts[0])


def _local_cell_id_is_numeric(row: dict[str, Any]) -> bool:
    for key, value in row.items():
        if _normalize_key(key) == 'localcellid':
            text = str(value or '').strip()
            if not text:
                return False
            if _is_known_field_name(text) or _looks_like_mml_parameter_name(text):
                return False
            return _is_numeric_cell_id(text)
    return True


def _drop_misparsed_cell_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove rows where Local Cell ID holds a parameter name instead of a number."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        if any(_is_garbage_row_key(str(key)) for key in row):
            continue
        has_lcid = any(_normalize_key(key) == 'localcellid' for key in row)
        if has_lcid and not _local_cell_id_is_numeric(row):
            continue
        if _row_has_parameter_values(row):
            continue
        kept.append(row)
    return kept


def _rows_look_like_cell_data(rows: list[dict[str, Any]]) -> bool:
    rows = _drop_misparsed_cell_rows(rows)
    if not rows:
        return False
    with_lcid = [row for row in rows if any(_normalize_key(k) == 'localcellid' for k in row)]
    if not with_lcid:
        return bool(rows)
    good = sum(1 for row in with_lcid if _local_cell_id_is_numeric(row))
    return good >= max(1, int(len(with_lcid) * 0.5))


_VERTICAL_EQUALS_RE = re.compile(r'\s=\s')
_CONTINUATION_KEY = '__continuation__'


def _is_vertical_equals_line(stripped: str) -> bool:
    return bool(_VERTICAL_EQUALS_RE.search(stripped or ''))


def _looks_like_vertical_equals_report(lines: list[str]) -> bool:
    """True for classic U2020 blocks: ``Parameter Name  =  Value``."""
    equals_lines = 0
    total = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('+++') or stripped.startswith('---'):
            continue
        if _SKIP_LINE_RE.match(stripped) or _is_status_text(stripped):
            continue
        if stripped.startswith('(') and 'results' in stripped.lower():
            continue
        if stripped.startswith('%%') or stripped.lower().startswith('display '):
            continue
        total += 1
        if _is_vertical_equals_line(stripped):
            equals_lines += 1
    if total < 2:
        return False
    return equals_lines >= max(2, int(total * 0.5))


def _parse_key_value_line(stripped: str) -> tuple[str, str] | None:
    """Parse ``Key = Value``, ``Key  Value``, or ``Key\\tValue`` lines."""
    if not stripped or _SKIP_LINE_RE.match(stripped) or _is_status_text(stripped):
        return None
    if '=' in stripped and not stripped.strip().startswith('('):
        key, _, value = stripped.partition('=')
        key, value = key.strip(), value.strip()
        if not key:
            return _CONTINUATION_KEY, value
    elif '\t' in stripped:
        parts = [p.strip() for p in stripped.split('\t') if p.strip()]
        if len(parts) != 2:
            return None
        key, value = parts[0], parts[1]
    else:
        parts = _split_columns(stripped)
        if len(parts) != 2:
            return None
        key, value = parts[0], parts[1]
    if key == _CONTINUATION_KEY:
        return _CONTINUATION_KEY, value
    if not key or _is_status_key(key):
        return None
    return key, value


def _is_false_horizontal_header(cols: list[str]) -> bool:
    """``Local Cell ID  1`` is a vertical pair, not a wide table header."""
    if len(cols) != 2:
        return False
    return (
        _normalize_key(cols[0]) in _CELL_BLOCK_START_KEYS
        and _is_numeric_cell_id(cols[1])
    )


def _looks_like_vertical_pairs(lines: list[str]) -> bool:
    """
    True when the report is ``Parameter  Value`` lines (double-space separated).

    Wide rows (3+ columns) indicate a horizontal table unless they are title rows
    stripped by ``_strip_column_header_lines``.
    """
    pair_lines = 0
    wide_lines = 0
    total = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('+++') or stripped.startswith('---'):
            continue
        if _SKIP_LINE_RE.match(stripped) or _is_status_text(stripped):
            continue
        if stripped.startswith('(') and 'results' in stripped.lower():
            continue
        parts = _split_columns(stripped)
        if len(parts) >= 3 and _is_likely_column_header_line(parts):
            continue
        total += 1
        if len(parts) > 2:
            wide_lines += 1
        elif len(parts) == 2:
            pair_lines += 1
    if total < 2:
        return False
    if wide_lines > 0:
        return False
    return pair_lines >= max(2, int(total * 0.8))


def _looks_like_hybrid_vertical_report(lines: list[str]) -> bool:
    """
    Some U2020 builds print a wide column-title row, then vertical pairs:

        Local Cell ID  Cell Name  Csg indicator  ...
        Local Cell ID  1
        Cell Name  foo
    """
    meaningful: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('+++') or stripped.startswith('---'):
            continue
        if _SKIP_LINE_RE.match(stripped) or _is_status_text(stripped):
            continue
        if stripped.startswith('(') and 'results' in stripped.lower():
            continue
        meaningful.append(stripped)

    if len(meaningful) < 2:
        return False
    first_parts = _split_columns(meaningful[0])
    if not _is_likely_column_header_line(first_parts):
        return False
    pair_after_header = 0
    for line in meaningful[1:12]:
        parts = _split_columns(line)
        if _is_vertical_pair_line(parts):
            pair_after_header += 1
    return pair_after_header >= 1


def _parse_vertical_space_pairs(lines: list[str]) -> list[dict[str, Any]]:
    """Parse vertical ``Parameter  Value`` blocks into one dict per cell/MO instance."""
    lines = _strip_column_header_lines(lines)
    rows: list[dict[str, Any]] = []
    row: dict[str, Any] = {}

    def flush() -> None:
        nonlocal row
        if not row:
            return
        filtered = _filter_mml_rows([row])
        if filtered:
            rows.extend(filtered)
        row = {}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('+++') or stripped.startswith('---'):
            flush()
            continue
        parsed = _parse_key_value_line(stripped)
        if not parsed:
            continue
        key, value = parsed
        if key == _CONTINUATION_KEY:
            if not row:
                continue
            last_key = next(reversed(row))
            existing = str(row.get(last_key) or '').strip()
            row[last_key] = f'{existing}&{value}' if existing else value
            continue
        norm = _normalize_key(key)
        if norm in _CELL_BLOCK_START_KEYS and row:
            flush()
        row[key] = value

    flush()
    return rows


def _try_vertical_pair_parse(lines: list[str]) -> list[dict[str, Any]]:
    """Parse vertical pair reports, including hybrid header + body layouts."""
    rows = _parse_vertical_space_pairs(lines)
    return _filter_mml_rows(rows)


def _parse_data_only_horizontal_block(
    lines: list[str],
    start: int,
    *,
    header: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse consecutive wide numeric-start rows (no header line in report)."""
    data_rows: list[list[str]] = []
    j = start
    while j < len(lines):
        stripped = lines[j].strip()
        if not stripped:
            if data_rows:
                break
            j += 1
            continue
        if stripped.startswith('---') or stripped.startswith('('):
            break
        if _SKIP_LINE_RE.match(stripped) or _is_status_text(stripped):
            j += 1
            continue
        cols = _split_columns(stripped)
        if not _is_likely_horizontal_data_row(cols):
            break
        data_rows.append(cols)
        j += 1

    if not data_rows:
        return [], start

    width = max(len(row) for row in data_rows)
    if header and len(header) >= width:
        column_names = header[:width]
        if len(header) < width:
            column_names = header + [f'Column {idx}' for idx in range(len(header), width)]
    else:
        column_names = ['Local cell ID'] + [f'Column {idx}' for idx in range(1, width)]

    rows: list[dict[str, Any]] = []
    for cols in data_rows:
        row = {
            column_names[idx]: cols[idx] if idx < len(cols) else ''
            for idx in range(len(column_names))
        }
        rows.append(row)
    return rows, j


def _is_mashed_cell_row_key(key: str) -> bool:
    parts = _split_columns(str(key or '').strip())
    return bool(parts) and _is_numeric_cell_id(parts[0])


def _is_garbage_mml_row(row: dict[str, Any]) -> bool:
    """True when a row was misparsed from a headerless horizontal table."""
    keys = [str(key) for key in row if str(key) not in ('NE', '_mml_warnings', 'report')]
    if not keys:
        return True
    if any(_normalize_key(key) == 'localcellid' for key in keys):
        return not _local_cell_id_is_numeric(row)
    if all(_is_mashed_cell_row_key(key) for key in keys):
        return True
    if len(keys) >= 3 and all(str(key).replace('.', '', 1).isdigit() for key in keys):
        return True
    return False


def _infer_canonical_headers(rows: list[dict[str, Any]]) -> list[str] | None:
    best: list[str] | None = None
    for row in rows:
        if _is_garbage_mml_row(row):
            continue
        keys = [str(key) for key in row if str(key) not in ('NE', '_mml_warnings', 'report')]
        if not any(_normalize_key(key) == 'localcellid' for key in keys):
            continue
        if not _local_cell_id_is_numeric(row):
            continue
        if len(keys) >= 3 and (best is None or len(keys) > len(best)):
            best = keys
    return best


def _repair_garbage_row(
    row: dict[str, Any],
    headers: list[str],
) -> list[dict[str, Any]]:
    meta = {key: row[key] for key in ('NE', '_mml_warnings') if key in row}
    rebuilt: list[dict[str, Any]] = []
    for key, value in row.items():
        if str(key) in meta:
            continue
        if not (_is_mashed_cell_row_key(str(key)) or str(key).replace('.', '', 1).isdigit()):
            continue
        line = f'{key}  {value}'
        cols = _split_columns(line)
        if len(cols) < 2:
            continue
        mapped = {
            headers[idx]: cols[idx] if idx < len(cols) else ''
            for idx in range(len(headers))
        }
        mapped.update(meta)
        rebuilt.append(mapped)
    return rebuilt


def _uses_generic_column_names(row: dict[str, Any]) -> bool:
    return any(str(key).startswith('Column ') for key in row)


def _generic_row_values(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    lcid_key = next(
        (key for key in row if _normalize_key(str(key)) == 'localcellid'),
        None,
    )
    if lcid_key is not None:
        values.append(str(row.get(lcid_key) or ''))
    idx = 1
    while f'Column {idx}' in row:
        values.append(str(row.get(f'Column {idx}') or ''))
        idx += 1
    return values


def _remap_generic_row(row: dict[str, Any], headers: list[str]) -> dict[str, Any]:
    values = _generic_row_values(row)
    meta = {key: row[key] for key in ('NE', '_mml_warnings') if key in row}
    mapped = {
        headers[idx]: values[idx] if idx < len(values) else ''
        for idx in range(len(headers))
    }
    mapped.update(meta)
    return mapped


def repair_mml_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Fix rows misparsed from headerless wide tables (e.g. LST CELLMLB on some NEs).

    Uses column names from correctly parsed rows in the same batch.
    """
    if not rows:
        return rows
    canonical = _infer_canonical_headers(rows)
    if not canonical:
        return rows

    repaired: list[dict[str, Any]] = []
    for row in rows:
        if _is_garbage_mml_row(row):
            fixed = _repair_garbage_row(row, canonical)
            if fixed:
                repaired.extend(fixed)
                continue
        elif _uses_generic_column_names(row):
            repaired.append(_remap_generic_row(row, canonical))
            continue
        repaired.append(row)
    return _drop_misparsed_cell_rows(repaired)


def _score_parsed_rows(rows: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Higher is better. Returns (score, cleaned rows)."""
    cleaned = _drop_misparsed_cell_rows(_filter_mml_rows(rows))
    if not cleaned:
        return 0, cleaned
    score = len(cleaned) * 10
    has_lcid = any(
        any(_normalize_key(str(key)) == 'localcellid' for key in row)
        for row in cleaned
    )
    for row in cleaned:
        if any(_normalize_key(str(key)) == 'localcellid' for key in row):
            score += 20
        if _row_has_parameter_values(row):
            score -= 100
    if not has_lcid:
        score = max(0, score - len(cleaned) * 8)
    return score, cleaned


def _choose_best_rows(
    horizontal: list[dict[str, Any]],
    vertical: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hor_score, hor_clean = _score_parsed_rows(horizontal)
    ver_score, ver_clean = _score_parsed_rows(vertical)
    ver_has_lcid = any(
        any(_normalize_key(str(key)) == 'localcellid' for key in row)
        for row in ver_clean
    )
    hor_has_lcid = any(
        any(_normalize_key(str(key)) == 'localcellid' for key in row)
        for row in hor_clean
    )
    if ver_has_lcid and not hor_has_lcid:
        return ver_clean
    if hor_has_lcid and not ver_has_lcid:
        return hor_clean
    if ver_score > hor_score:
        return ver_clean
    if hor_score > ver_score:
        return hor_clean
    if ver_clean:
        return ver_clean
    return hor_clean


def parse_mml_report(report: str) -> list[dict[str, Any]]:
    """Return list of row dicts parsed from an MML report string."""
    if not report:
        return []

    text = report.replace('\r\n', '\n').replace('\r', '\n')
    lines = [ln.rstrip() for ln in text.split('\n')]

    if _looks_like_vertical_equals_report(lines):
        rows = _drop_misparsed_cell_rows(_try_vertical_pair_parse(lines))
        if rows:
            return rows

    if _looks_like_hybrid_vertical_report(lines):
        rows = _drop_misparsed_cell_rows(_try_vertical_pair_parse(lines))
        if rows:
            return rows

    vertical_rows = _try_vertical_pair_parse(lines)
    horizontal_rows = _parse_horizontal_tables(lines)
    chosen = _choose_best_rows(horizontal_rows, vertical_rows)
    if chosen:
        return chosen

    rows: list[dict[str, Any]] = []
    rows.extend(_parse_vertical_blocks(lines))
    return _drop_misparsed_cell_rows(_filter_mml_rows(rows))


def _parse_horizontal_tables(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending_header: list[str] | None = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('+++') or line.startswith('---') or line.startswith('%'):
            i += 1
            continue
        if _is_vertical_equals_line(line):
            i += 1
            continue
        if _SKIP_LINE_RE.match(line):
            i += 1
            continue
        if line.startswith('(') and 'results' in line.lower():
            i += 1
            continue

        cols = _split_columns(line)
        if len(cols) < 2:
            i += 1
            continue
        if _is_status_header(cols):
            i += 1
            continue
        if _is_false_horizontal_header(cols):
            i += 1
            continue

        if _is_likely_horizontal_data_row(cols):
            block_rows, next_i = _parse_data_only_horizontal_block(
                lines,
                i,
                header=pending_header,
            )
            if block_rows:
                rows.extend(block_rows)
                pending_header = None
                i = next_i
                continue

        # Header row: next non-empty line should be blank, then data rows follow.
        header = cols
        if _is_likely_column_header_line(cols):
            pending_header = cols
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1

        data_started = False
        header_confirmed = _is_likely_column_header_line(header)
        while j < len(lines):
            data_line = lines[j].strip()
            if not data_line:
                if data_started:
                    break
                j += 1
                continue
            if _is_vertical_equals_line(data_line):
                j += 1
                continue
            if data_line.startswith('---') or data_line.startswith('('):
                break
            if _SKIP_LINE_RE.match(data_line) or _is_status_text(data_line):
                j += 1
                continue
            data_cols = _split_columns(data_line)
            if len(data_cols) >= 2:
                if _is_status_header(data_cols):
                    j += 1
                    continue
                if _is_likely_column_header_line(data_cols):
                    if not data_started:
                        header = data_cols
                        pending_header = data_cols
                        header_confirmed = True
                        j += 1
                        continue
                    break
                if len(header) >= 3 and _is_vertical_pair_line(data_cols):
                    j += 1
                    continue
                if not header_confirmed:
                    j += 1
                    continue
                row = {}
                for idx, key in enumerate(header):
                    row[key] = data_cols[idx] if idx < len(data_cols) else ''
                rows.append(row)
                data_started = True
            j += 1

        if data_started:
            i = j
        else:
            i += 1
    return rows


def _parse_vertical_blocks(lines: list[str]) -> list[dict[str, Any]]:
    row: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('+++') or stripped.startswith('---'):
            if row:
                filtered = _filter_mml_rows([row])
                if filtered:
                    rows.extend(filtered)
                row = {}
            continue
        parsed = _parse_key_value_line(stripped)
        if not parsed:
            continue
        key, value = parsed
        if key == _CONTINUATION_KEY:
            if not row:
                continue
            last_key = next(reversed(row))
            existing = str(row.get(last_key) or '').strip()
            row[last_key] = f'{existing}&{value}' if existing else value
            continue
        row[key] = value
    if row:
        filtered = _filter_mml_rows([row])
        if filtered:
            rows.extend(filtered)
    return rows


def normalize_mml_command(command: str) -> str:
    """Normalize MML to U2020 form ``COMMAND:;`` (colon required before semicolon)."""
    cmd = (command or '').strip()
    if not cmd:
        return ''
    if cmd.endswith(':;'):
        return cmd
    if cmd.endswith(';'):
        return f'{cmd[:-1].rstrip(":")}:;'
    if cmd.endswith(':'):
        return f'{cmd};'
    return f'{cmd}:;'
