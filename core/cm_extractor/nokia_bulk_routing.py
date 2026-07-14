"""Route Nokia CM extracts between Open API and CM Operations bulk export."""

from __future__ import annotations

import os
from typing import Any

from core.cm_extractor.config import nokia_export_ssh_settings

# MO abbreviations that are typically high-volume (many instances per cell/site).
_DEFAULT_BULK_MO_ABBREVIATIONS = frozenset({
    'LNHOIF',
    'LNHOIFSPARE',
    'LNREL',
    'LNRELG',
    'LNRELGNBCELL',
    'LNRELN',
    'LNRELT',
    'LNRELW',
    'LNRELX',
    'LNRELSPARE',
    'LNRELGSPARE',
    'LNRELWSPARE',
    'LNRELXSPARE',
})


def bulk_mo_abbreviations() -> frozenset[str]:
    raw = (os.environ.get('CM_BULK_MO_CLASSES') or '').strip()
    if not raw:
        return _DEFAULT_BULK_MO_ABBREVIATIONS
    return frozenset(
        token.strip().upper()
        for part in raw.split(',')
        for token in [part.strip()]
        if token
    )


def _mo_abbreviation(mo_class_id: str) -> str:
    token = (mo_class_id or '').strip()
    if ':' in token:
        return token.split(':', 1)[1].strip().upper()
    return token.upper()


def selection_prefers_bulk(sel: dict[str, Any], *, site_count: int = 1) -> bool:
    mo_class_id = (sel.get('mo_class_id') or sel.get('id') or '').strip()
    abbr = _mo_abbreviation(mo_class_id)
    if abbr not in bulk_mo_abbreviations():
        return False
    export_mode = (sel.get('export_mode') or '').strip().lower()
    if export_mode == 'full':
        return True
    params = [p for p in (sel.get('parameters') or []) if p]
    if site_count >= 10 and params:
        return True
    if len(params) >= 20:
        return True
    return len(params) >= 40


def should_use_bulk_export(
    *,
    scope_level: str,
    site_ids: list[str],
    selections: list[dict[str, Any]],
) -> bool:
    """Use CM Operations Import_Export when SFTP is configured and MO scope is heavy."""
    level = (scope_level or 'MRBTS').strip().upper()
    if level not in ('MRBTS', 'RNC', 'BSC'):
        return False
    if not nokia_export_ssh_settings().get('configured'):
        return False
    if not selections:
        return False
    if level in ('RNC', 'BSC'):
        return True
    site_count = len(site_ids)
    if site_count < 1:
        return False
    return any(selection_prefers_bulk(sel, site_count=site_count) for sel in selections)
