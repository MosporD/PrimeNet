"""Route Nokia CM extracts between Open API and CM Operations bulk export."""

from __future__ import annotations

import os
from typing import Any

from core.cm_extractor.config import nokia_export_ssh_settings

# Neighbor / HO-interface MOs: tens to hundreds of instances per cell.
# Matching is by prefix so SPARE / IRAT variants (LNRELW, LNADJG, …) are included.
_HIGH_CARDINALITY_MO_PREFIXES = ('LNREL', 'LNADJ', 'LNHOIF')

# Explicit names kept for tests / env overrides that replace the default set.
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
    'LNADJ',
    'LNADJG',
    'LNADJGNB',
    'LNADJL',
    'LNADJN',
    'LNADJNL',
    'LNADJT',
    'LNADJW',
    'LNADJX',
    'LNADJSPARE',
    'LNADJGSPARE',
    'LNADJGNBSPARE',
    'LNADJLSPARE',
    'LNADJWSPARE',
    'LNADJXSPARE',
})


def bulk_mo_abbreviations() -> frozenset[str]:
    extra = (os.environ.get('CM_BULK_MO_CLASSES') or '').strip()
    names = set(_DEFAULT_BULK_MO_ABBREVIATIONS)
    if extra:
        names.update(
            token.strip().upper()
            for part in extra.split(',')
            for token in [part.strip()]
            if token
        )
    return frozenset(names)


def _mo_abbreviation(mo_class_id: str) -> str:
    token = (mo_class_id or '').strip()
    if ':' in token:
        return token.split(':', 1)[1].strip().upper()
    return token.upper()


def is_high_cardinality_mo(mo_class_id: str) -> bool:
    """True for neighbor / HO-interface classes whose instance count dominates query cost."""
    abbr = _mo_abbreviation(mo_class_id)
    return any(abbr == prefix or abbr.startswith(prefix) for prefix in _HIGH_CARDINALITY_MO_PREFIXES)


def is_bulk_mo_abbreviation(mo_class_id: str) -> bool:
    abbr = _mo_abbreviation(mo_class_id)
    if is_high_cardinality_mo(abbr):
        return True
    return abbr in bulk_mo_abbreviations()


def selection_prefers_bulk(sel: dict[str, Any], *, site_count: int = 1) -> bool:
    """
    Prefer CM Operations Import_Export for high-cardinality neighbor MOs.

    Instance count (not parameter count or site count) dominates runtime. A
    two-site LNREL/LNADJ Open API dump that falls back to all-PLMN can take
    minutes; Import_Export is scoped to the selected MRBTS DNs.
    """
    del site_count  # cardinality of the MO class matters, not how many sites
    mo_class_id = (sel.get('mo_class_id') or sel.get('id') or '').strip()
    return is_bulk_mo_abbreviation(mo_class_id)


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
