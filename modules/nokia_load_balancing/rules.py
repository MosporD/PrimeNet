"""AMLE layer mapping and parameter proposal rules."""

from __future__ import annotations

import re
from typing import Any

from core.cm_extractor.site_catalog import (
    _known_nokia_metadata_site_ids,
    resolve_nokia_metadata_site_id,
)

from . import config

_SECTOR_LETTER: dict[int, str] = {
    **{k: "A" for k in [1, 31, 71, 61, 51, 81]},
    **{k: "B" for k in [2, 32, 72, 82, 62, 52]},
    **{k: "C" for k in [3, 33, 73, 63, 53, 83]},
    **{k: "D" for k in [7, 37, 77, 64, 54, 87, 67, 57, 74, 4, 34, 84]},
    **{k: "E" for k in [9, 39, 79, 69, 59, 89]},
    **{k: "F" for k in [6, 36, 76, 66, 56, 86]},
}

_DN_MRBTS = re.compile(r"/MRBTS-(\d+)(?:/|$)")
_DN_LNBTS = re.compile(r"/LNBTS-(\d+)(?:/|$)")
_DN_LNCEL = re.compile(r"/LNCEL-(\d+)(?:/|$)")
_DN_AMLEPR = re.compile(r"/AMLEPR-(\d+)(?:/|$)")


def parse_sector_id(sector_id: str) -> tuple[str, str]:
    """Parse ``1201_A`` or ``1201-A`` into (mrbts, letter)."""
    token = (sector_id or "").strip().replace("-", "_")
    parts = token.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid sector id '{sector_id}' — expected format MRBTS_Letter (e.g. 1201_A)")
    return parts[0], parts[1].upper()


def sector_letter(lncel: int) -> str:
    return _SECTOR_LETTER.get(int(lncel), "Other")


# targetCarrierFreq values that point at each layer's carrier (co-sector AMLEPR target).
_LAYER_TARGET_FREQS: dict[str, frozenset[int]] = {
    "L18": frozenset({1850}),
    "L9": frozenset({3749, 3750}),
    "L21": frozenset({300, 325}),
    "L18+": frozenset({1250}),
}


def layer_from_lncel(lncel: int | str) -> str:
    """
    Map LNCEL id to throughput layer — same Excel IFS used in Network Balance:

    OR(1<=x<=9, 50<=x<=69) → L18 | 30<=x<=39 → L9 | 71<=x<=79 → L21 | 81<=x<=89 → L18+
    """
    try:
        x = int(lncel)
    except (TypeError, ValueError):
        return "Other"
    if (1 <= x <= 9) or (50 <= x <= 69):
        return "L18"
    if 30 <= x <= 39:
        return "L9"
    if 71 <= x <= 79:
        return "L21"
    if 81 <= x <= 89:
        return "L18+"
    return "Other"


def source_layer(lncel: int) -> str:
    return layer_from_lncel(lncel)


def lncels_for_sector_letter(letter: str) -> set[int]:
    """All LNCEL ids that belong to a co-sector letter (A–F)."""
    token = (letter or "").strip().upper()
    return {lncel for lncel, sector in _SECTOR_LETTER.items() if sector == token}


def target_layer_from_sector(sector_lncels: set[int], target_freq: Any) -> str:
    """
    Resolve target layer via co-sector LNCEL + ``targetCarrierFreq``.

    ``targetCarrierFreq`` selects which co-sector carrier is targeted; the layer
    label always comes from ``layer_from_lncel`` on the matching LNCEL.
    """
    try:
        freq = int(float(target_freq))
    except (TypeError, ValueError):
        return "Other"
    for lncel in sector_lncels:
        layer = layer_from_lncel(lncel)
        if freq in _LAYER_TARGET_FREQS.get(layer, ()):
            return layer
    return "Other"


def target_layer(earfcn: Any) -> str:
    """Deprecated alias — prefer ``target_layer_from_sector`` when sector LNCELs are known."""
    try:
        freq = int(float(earfcn))
    except (TypeError, ValueError):
        return "Other"
    for layer, freqs in _LAYER_TARGET_FREQS.items():
        if freq in freqs:
            return layer
    return "Other"


def highest_lowest_layer(throughput: dict[str, float | None]) -> tuple[str | None, str | None]:
    values = {
        layer: float(value)
        for layer, value in throughput.items()
        if layer in config.THROUGHPUT_LAYERS and value is not None and float(value) > 0
    }
    if len(values) < config.MIN_ACTIVE_LAYERS:
        return None, None
    highest = max(values, key=values.get)
    lowest = min(values, key=values.get)
    if config.SKIP_TIED_LAYERS and highest == lowest:
        return None, None
    return highest, lowest


def qualifies_highest_lowest_pair(
    source: str,
    target: str,
    highest: str,
    lowest: str,
) -> tuple[bool, bool]:
    """
    True when this AMLEPR row is a co-sector link between the highest and lowest layers.

    AMLE is only between co-sector carriers: source layer comes from LNCEL on the row's
    cell via ``layer_from_lncel``; target layer is resolved from ``targetCarrierFreq``
    against co-sector LNCEL ids using the same mapping. We adjust only the two directed
    edges highest↔lowest (e.g. L18→L9 and L9→L18), not other layer pairs in the sector.

    Returns ``(qualifies, is_highest_source)`` where ``is_highest_source`` is True for
    highest→lowest (reduce aggressiveness) and False for lowest→highest (increase).
    """
    if source == highest and target == lowest:
        return True, True
    if source == lowest and target == highest:
        return True, False
    return False, False


def missing_hl_direction_warnings(
    sector_id: str,
    highest: str,
    lowest: str,
    present: set[tuple[str, str]],
) -> list[str]:
    """Flag incomplete highest↔lowest AMLEPR configuration (one direction only)."""
    warnings: list[str] = []
    has_high_to_low = (highest, lowest) in present
    has_low_to_high = (lowest, highest) in present
    if has_high_to_low and not has_low_to_high:
        warnings.append(
            f"Sector {sector_id}: missing AMLEPR {lowest}→{highest} "
            f"(reverse of existing {highest}→{lowest}) — configuration gap"
        )
    if has_low_to_high and not has_high_to_low:
        warnings.append(
            f"Sector {sector_id}: missing AMLEPR {highest}→{lowest} "
            f"(reverse of existing {lowest}→{highest}) — configuration gap"
        )
    return warnings


def propose_value(current: Any, param: str, *, is_highest: bool, is_lowest: bool) -> tuple[float | None, int]:
    if param not in config.AMLE_PARAMS:
        return None, 0
    try:
        base = float(current)
    except (TypeError, ValueError):
        return None, 0

    if is_highest:
        delta = config.HIGHEST_LAYER_DELTAS.get(param, 0)
    elif is_lowest:
        delta = config.LOWEST_LAYER_DELTAS.get(param, 0)
    else:
        delta = 0

    proposed = max(config.PARAM_MIN, min(config.PARAM_MAX, base + delta))
    return proposed, delta


def propose_parameter_set(
    row: dict[str, Any],
    *,
    is_highest: bool,
    is_lowest: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[str]]:
    """
    Propose all AMLE parameters together — all-or-nothing.

    Returns ``(parameters, proposed_values, blockers)``. ``parameters`` is filled
    only when every AMLE param is present and each proposed value differs from
    current (after clamp). ``proposed_values`` always holds computed targets for review.
    """
    proposed_values: dict[str, Any] = {}
    parameters: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []

    for param in config.AMLE_PARAMS:
        if param not in row:
            blockers.append(f"missing {param}")
            continue
        current = row.get(param)
        proposed, delta = propose_value(current, param, is_highest=is_highest, is_lowest=is_lowest)
        if proposed is None:
            blockers.append(f"{param}: invalid current value")
            continue
        proposed_values[param] = proposed
        if delta == 0:
            blockers.append(f"{param}: no adjustment rule")
            continue
        if str(proposed) == str(current):
            blockers.append(f"{param}: clamped at {current}")
            continue
        parameters[param] = {"current": current, "proposed": proposed, "delta": delta}

    if len(parameters) == len(config.AMLE_PARAMS):
        return parameters, proposed_values, []
    return {}, proposed_values, blockers


def parse_dn_parts(dn: str) -> tuple[str | None, str | None]:
    dn = str(dn or "").strip()
    mrbts_m = _DN_MRBTS.search(dn)
    lncel_m = _DN_LNCEL.search(dn)
    mrbts = mrbts_m.group(1) if mrbts_m else None
    lncel = lncel_m.group(1) if lncel_m else None
    return mrbts, lncel


def amlepr_identifiers_from_row(row: dict[str, Any], dn: str = "") -> dict[str, str | None]:
    """Extract MRBTS, LNBTS, LNCEL, AMLEPR id from CM row columns or DN."""
    dn = str(dn or row.get("DN") or row.get("distName") or "").strip()
    lnbts_m = _DN_LNBTS.search(dn) if dn else None
    amlepr_m = _DN_AMLEPR.search(dn) if dn else None
    _, lncel_from_dn = parse_dn_parts(dn) if dn else (None, None)
    mrbts_from_dn, _ = parse_dn_parts(dn) if dn else (None, None)

    def _col(name: str) -> str | None:
        value = row.get(name)
        if value is None or value == "":
            return None
        return str(value).strip()

    return {
        "mrbts": _col("MRBTS") or mrbts_from_dn,
        "lnbts": _col("LNBTS") or (lnbts_m.group(1) if lnbts_m else None),
        "lncel": _col("LNCEL") or lncel_from_dn,
        "amlepr": _col("AMLEPR") or (amlepr_m.group(1) if amlepr_m else None),
    }


def _metadata_mrbts(raw_mrbts: Any, *, known_metadata_ids: set[str] | None = None) -> str | None:
    token = str(raw_mrbts or "").strip()
    if not token:
        return None
    known = known_metadata_ids if known_metadata_ids is not None else _known_nokia_metadata_site_ids()
    return resolve_nokia_metadata_site_id(token, known_metadata_ids=known) or token


def sector_id_from_parts(
    mrbts: Any,
    lncel: Any,
    *,
    known_metadata_ids: set[str] | None = None,
) -> str | None:
    """Build ``5635_A`` from site id + LNCEL using the Network Balance sector formula."""
    meta_mrbts = _metadata_mrbts(mrbts, known_metadata_ids=known_metadata_ids)
    if not meta_mrbts:
        return None
    try:
        letter = sector_letter(int(lncel))
    except (TypeError, ValueError):
        return None
    if letter == "Other":
        return None
    return f"{meta_mrbts}_{letter}"


def sector_id_from_row(
    row: dict[str, Any],
    *,
    known_metadata_ids: set[str] | None = None,
) -> str | None:
    """
    Derive sector id from CM extract row — same logic as the Excel CONCAT formula.

    Prefers explicit MRBTS/LNCEL columns (manual AMLE export shape); falls back to DN.
    """
    mrbts = row.get("MRBTS")
    lncel = row.get("LNCEL")
    if mrbts is not None and lncel is not None:
        sid = sector_id_from_parts(mrbts, lncel, known_metadata_ids=known_metadata_ids)
        if sid:
            return sid

    dn = str(row.get("DN") or row.get("distName") or "").strip()
    if dn:
        return sector_id_from_dn(dn, known_metadata_ids=known_metadata_ids)
    return None


def sector_id_from_dn(
    dn: str,
    *,
    known_metadata_ids: set[str] | None = None,
) -> str | None:
    mrbts, lncel = parse_dn_parts(dn)
    if not mrbts or not lncel:
        return None
    return sector_id_from_parts(mrbts, lncel, known_metadata_ids=known_metadata_ids)


def normalize_throughput(raw: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {layer: None for layer in config.THROUGHPUT_LAYERS}
    for layer in config.THROUGHPUT_LAYERS:
        if layer not in raw:
            continue
        value = raw.get(layer)
        if value is None or value == "":
            continue
        try:
            out[layer] = float(value)
        except (TypeError, ValueError):
            continue
    return out
