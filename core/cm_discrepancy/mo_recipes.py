"""MO coverage config for the CM discrepancy audit.

Reads ``data/cm_discrepancy_mo_recipes.json`` (admin-editable, no code change
needed to adjust MO coverage). An optional override file with the same schema
can be pointed to via ``CM_DISCREPANCY_MO_RECIPES``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from sync_config import PROJECT_ROOT

DEFAULT_RECIPES_PATH = os.path.join(PROJECT_ROOT, 'data', 'cm_discrepancy_mo_recipes.json')

NOKIA_SCOPES = ('MRBTS', 'BSC', 'RNC')


def recipes_path() -> str:
    override = (os.getenv('CM_DISCREPANCY_MO_RECIPES') or '').strip()
    return override or DEFAULT_RECIPES_PATH


def load_recipes() -> dict[str, Any]:
    path = recipes_path()
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f'MO recipes file must contain a JSON object: {path}')
    return data


def audit_options(recipes: dict[str, Any] | None = None) -> dict[str, Any]:
    recipes = recipes if recipes is not None else load_recipes()
    options = recipes.get('options') or {}
    return {
        'include_empty_values': bool(options.get('include_empty_values', False)),
    }


def huawei_mos(recipes: dict[str, Any] | None = None) -> list[str]:
    recipes = recipes if recipes is not None else load_recipes()
    section = recipes.get('huawei') or {}
    return [str(mo).strip().upper() for mo in (section.get('mos') or []) if str(mo).strip()]


def nokia_mos_by_scope(recipes: dict[str, Any] | None = None) -> dict[str, list[str]]:
    recipes = recipes if recipes is not None else load_recipes()
    section = recipes.get('nokia') or {}
    out: dict[str, list[str]] = {}
    for scope in NOKIA_SCOPES:
        mos = [str(mo).strip() for mo in (section.get(scope) or []) if str(mo).strip()]
        if mos:
            out[scope] = mos
    return out
