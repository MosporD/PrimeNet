"""Lite cell-identity normalizer for Cases correlator/scorecard joins only.

Does NOT change Network Health / shared pm_helpers Huawei LocalCell Id preference.
"""

from __future__ import annotations

import re


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_cell_key(value: object) -> str:
    """Lowercase compact key for fuzzy equality (drops separators)."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return _NON_ALNUM.sub("", text)


def cell_aliases(value: object) -> set[str]:
    """Return matching keys for a cell label (raw + normalized)."""
    text = str(value or "").strip()
    if not text:
        return set()
    keys = {text.lower(), normalize_cell_key(text)}
    # Split common vendor patterns: SITE_CELL, SITE-CELL, SITE/CELL
    for part in re.split(r"[|/_;]+", text):
        p = part.strip()
        if p:
            keys.add(p.lower())
            keys.add(normalize_cell_key(p))
    return {k for k in keys if k}


def cells_match(a: object, b: object) -> bool:
    aa = cell_aliases(a)
    bb = cell_aliases(b)
    if not aa or not bb:
        return False
    return bool(aa & bb)


def filter_rows_for_cells(rows: list[dict], cells: list[str], *, cell_field: str = "cell_name") -> list[dict]:
    """Keep rows whose cell field matches any target cell alias."""
    if not cells:
        return []
    targets: set[str] = set()
    for c in cells:
        targets |= cell_aliases(c)
    if not targets:
        return []
    out: list[dict] = []
    for row in rows or []:
        name = row.get(cell_field) or row.get("cell") or row.get("cell_name") or ""
        if cell_aliases(name) & targets:
            out.append(row)
    return out


def expand_cell_list(cells: list[str] | None) -> list[str]:
    """Deduplicate cells preserving order, keeping display form."""
    out: list[str] = []
    seen: set[str] = set()
    for c in cells or []:
        text = str(c or "").strip()
        if not text:
            continue
        key = normalize_cell_key(text) or text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
