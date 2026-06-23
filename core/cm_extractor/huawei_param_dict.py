"""
Huawei MO/parameter baseline built from the bundled MO & Parameter Reference (the
"parameter dictionary"). Huawei's NBI exposes no MO metadata service, so we derive a
read-only catalog from the offline MOM HTML export under
``modules/parameter_dictionary/huawei_params``.

Each ``*/mo/<MO>.html`` page lists the MO's related MML commands and its parameters.
We keep only MOs that support a **read** command (``LST`` or ``DSP``) and expose their
parameters as children, since PrimeNet CM extraction is read-only.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
PARAM_DICT_DIR = _REPO_ROOT / 'modules' / 'parameter_dictionary' / 'huawei_params'
_CATALOG_PATH = _REPO_ROOT / 'data' / 'huawei_param_dict_catalog.json'

# Read-only MML verbs. PrimeNet never issues MOD/ADD/RMV.
_READ_VERBS = ('LST', 'DSP')

# Mode dir (first path segment) -> technology label fallback.
_DIR_TECH = {
    'ratg': '2G',
    'ratu': '3G',
    'ratl': '4G',
    'ratn': '5G',
    'ratr': 'Common',
    'comm': 'Common',
}

# Float a handful of frequently used radio MOs to the top of the picker.
_RECOMMENDED = frozenset({
    'CELL', 'ENODEBFUNCTION', 'EUTRANCELLTDD', 'EUTRANCELLFDD',
    'NRDUCELL', 'NRCELL', 'GNODEBFUNCTION', 'GNBCUFUNCTION',
    'UCELL', 'NODEBFUNCTION', 'GCELL', 'BTSFUNCTION', 'SECTOR', 'SECTOREQM',
})

# Regexes (the MOM HTML is regular and machine-generated).
_RE_TITLE = re.compile(r'<h1\s+class="topictitle1">(.*?)</h1>', re.IGNORECASE | re.DOTALL)
_RE_META_TITLE = re.compile(r'<title>(.*?)</title>', re.IGNORECASE | re.DOTALL)
_RE_IDENT = re.compile(r'<meta\s+name="DC\.Identifier"\s+content="([^"]*)"', re.IGNORECASE)
_RE_MODE = re.compile(r'<meta\s+name="Mode"\s+content="([^"]*)"', re.IGNORECASE)
_RE_PRODUCT = re.compile(r'<meta\s+name="product"\s+content="([^"]*)"', re.IGNORECASE)
_RE_MML_ANCHOR = re.compile(r'<a\s+href="\.\./mml/[^"]+">(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RE_PARAM_ROW = re.compile(
    r'<a\s+href="\.\./para/([^"#]+?)\.html(?:#[^"]*)?">(.*?)</a>\s*</td>\s*<td[^>]*>(.*?)</td>',
    re.IGNORECASE | re.DOTALL,
)
_RE_PARAM_ANCHOR = re.compile(
    r'<a\s+href="\.\./para/([^"#]+?)\.html(?:#[^"]*)?">(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_CACHE: dict[str, Any] = {}


def _clean_text(raw: str) -> str:
    no_tags = re.sub(r'<[^>]+>', ' ', raw or '')
    return html_lib.unescape(re.sub(r'\s+', ' ', no_tags).strip())


def _mode_to_tech(mode: str, mode_dir: str) -> str:
    upper = (mode or '').upper()
    techs: list[str] = []
    if 'GSM' in upper:
        techs.append('2G')
    if 'UMTS' in upper or 'WCDMA' in upper:
        techs.append('3G')
    if 'LTE' in upper:
        techs.append('4G')
    if 'NR' in upper or '5G' in upper:
        techs.append('5G')
    if len(techs) == 1:
        return techs[0]
    if len(techs) > 1:
        return 'Multi'
    return _DIR_TECH.get((mode_dir or '').lower(), 'Common')


def _read_commands(html: str) -> list[str]:
    """Return de-duped read-only commands (LST/DSP) in document order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _RE_MML_ANCHOR.findall(html):
        cmd = _clean_text(raw).upper()
        if not cmd:
            continue
        verb = cmd.split(' ', 1)[0]
        if verb in _READ_VERBS and cmd not in seen:
            seen.add(cmd)
            out.append(cmd)
    return out


def _parameters(html: str) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    by_name: dict[str, int] = {}
    for ref, name_raw, desc_raw in _RE_PARAM_ROW.findall(html):
        name = _clean_text(name_raw)
        if not name or name in by_name:
            continue
        by_name[name] = len(params)
        params.append({
            'id': name,
            'name': name,
            'ref': ref,
            'param_id': ref.split('-', 1)[-1] if '-' in ref else '',
            'description': _clean_text(desc_raw)[:400],
        })
    # Catch any anchors the row regex missed (e.g. structure variants).
    for ref, name_raw in _RE_PARAM_ANCHOR.findall(html):
        name = _clean_text(name_raw)
        if not name or name in by_name:
            continue
        by_name[name] = len(params)
        params.append({
            'id': name,
            'name': name,
            'ref': ref,
            'param_id': ref.split('-', 1)[-1] if '-' in ref else '',
            'description': '',
        })
    return params


def _parse_mo_page(path: Path, mode_dir: str) -> dict[str, Any] | None:
    try:
        html = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None

    all_read = _read_commands(html)
    if not all_read:
        return None  # write-only MO (ADD/MOD/RMV) — skip for read-only extraction.

    # MML object token for this MO (its own command target), from DC.Identifier or title.
    ident_m = _RE_IDENT.search(html)
    title_m = _RE_TITLE.search(html) or _RE_META_TITLE.search(html)
    label = _clean_text(title_m.group(1)) if title_m else ''
    obj_id = ((ident_m.group(1) if ident_m else '') or label).strip().upper()
    if not obj_id:
        return None

    # Keep only the read commands that target THIS MO; related commands on the page
    # (e.g. DSP CELLBYLOCATION on the CELL page) belong to other objects.
    own = [c for c in all_read if (c.split(' ', 1)[1].strip() if ' ' in c else '') == obj_id]
    if not own:
        return None  # no read command for this MO itself — not retrievable read-only.

    command = next((c for c in own if c.startswith('LST ')), own[0])

    mode_m = _RE_MODE.search(html)
    product_m = _RE_PRODUCT.search(html)
    products = [p.strip() for p in (product_m.group(1) if product_m else '').split(';') if p.strip()]
    tech = _mode_to_tech(mode_m.group(1) if mode_m else '', mode_dir)

    return {
        'id': obj_id,
        'ref_id': ident_m.group(1) if ident_m else '',
        'label': label or obj_id,
        'technology': tech,
        'group': tech,
        'command': command,
        'read_commands': own,
        'products': products,
        'recommended': obj_id in _RECOMMENDED,
        'parameters': _parameters(html),
    }


def _merge_entries(base: dict[str, Any], extra: dict[str, Any]) -> None:
    """Merge an MO that appears under more than one mode into the existing entry."""
    existing_params = {p['name'] for p in base['parameters']}
    for param in extra['parameters']:
        if param['name'] not in existing_params:
            existing_params.add(param['name'])
            base['parameters'].append(param)
    for cmd in extra['read_commands']:
        if cmd not in base['read_commands']:
            base['read_commands'].append(cmd)
    for prod in extra['products']:
        if prod not in base['products']:
            base['products'].append(prod)
    if base['technology'] != extra['technology']:
        base['technology'] = 'Multi'
        base['group'] = 'Multi'
    if base['command'].startswith('DSP ') and extra['command'].startswith('LST '):
        base['command'] = extra['command']
    base['recommended'] = base['recommended'] or extra['recommended']


def build_catalog() -> dict[str, Any]:
    """Parse all MO pages into a read-only MO/parameter catalog."""
    catalog: dict[str, dict[str, Any]] = {}
    page_count = 0

    if PARAM_DICT_DIR.is_dir():
        for mo_page in PARAM_DICT_DIR.glob('*/mo/*.html'):
            mode_dir = mo_page.relative_to(PARAM_DICT_DIR).parts[0]
            entry = _parse_mo_page(mo_page, mode_dir)
            if not entry:
                continue
            page_count += 1
            if entry['id'] in catalog:
                _merge_entries(catalog[entry['id']], entry)
            else:
                catalog[entry['id']] = entry

    mo_list = sorted(catalog.values(), key=lambda e: (not e['recommended'], e['technology'], e['id']))
    mo_columns = {e['id']: [p['name'] for p in e['parameters']] for e in mo_list}

    return {
        'built_at': time.time(),
        'source': 'parameter_dictionary',
        'mo_count': len(mo_list),
        'page_count': page_count,
        'param_count': sum(len(e['parameters']) for e in mo_list),
        'mo_catalog': mo_list,
        'mo_columns': mo_columns,
    }


def save_catalog(result: dict[str, Any] | None = None) -> Path:
    payload = result or build_catalog()
    _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CATALOG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    return _CATALOG_PATH


def load_catalog(*, rebuild: bool = False) -> dict[str, Any]:
    """Return the catalog from memory, then disk, building + caching on first use."""
    if not rebuild and _CACHE.get('mo_catalog'):
        return _CACHE

    if not rebuild and _CATALOG_PATH.is_file():
        try:
            payload = json.loads(_CATALOG_PATH.read_text(encoding='utf-8'))
            if payload.get('mo_catalog'):
                _CACHE.clear()
                _CACHE.update(payload)
                return _CACHE
        except (OSError, json.JSONDecodeError):
            pass

    payload = build_catalog()
    _CACHE.clear()
    _CACHE.update(payload)
    try:
        save_catalog(payload)
    except OSError:
        pass
    return _CACHE


def get_catalog_list() -> list[dict[str, Any]]:
    return list(load_catalog().get('mo_catalog') or [])


def get_mo_entry(mo_id: str) -> dict[str, Any] | None:
    token = (mo_id or '').strip().upper()
    if not token:
        return None
    for entry in load_catalog().get('mo_catalog') or []:
        if entry.get('id') == token:
            return entry
    return None
