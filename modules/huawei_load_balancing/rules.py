"""CellMLB parameter proposals from highest/lowest throughput layers."""

from __future__ import annotations

from typing import Any

from . import config


def _clamp(value: int) -> int:
    return max(config.PARAM_MIN, min(config.PARAM_MAX, int(value)))


def propose_parameter_set(
    current: dict[str, Any] | None,
    *,
    is_highest: bool,
    is_lowest: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, int], list[str]]:
    """Return (exportable params, proposed map, blockers). All-or-nothing like Nokia AMLE."""
    if is_highest == is_lowest:
        return {}, {}, ["Layer is neither unique highest nor unique lowest."]
    deltas = config.HIGHEST_LAYER_DELTAS if is_highest else config.LOWEST_LAYER_DELTAS
    current = current or {}
    proposed: dict[str, int] = {}
    blockers: list[str] = []
    params: dict[str, dict[str, Any]] = {}

    for name in config.CELLMLB_PARAMS:
        raw = current.get(name)
        if raw is None or str(raw).strip() == "":
            raw = config.DEFAULTS.get(name)
        try:
            cur = int(float(raw))
        except (TypeError, ValueError):
            blockers.append(f"missing {name}")
            continue
        nxt = _clamp(cur + int(deltas.get(name) or 0))
        if nxt == cur:
            blockers.append(f"{name}: clamped at {cur}")
            proposed[name] = nxt
            continue
        proposed[name] = nxt
        params[name] = {
            "parameter": name,
            "current": cur,
            "proposed": nxt,
            "delta": nxt - cur,
        }

    if blockers:
        return {}, proposed, blockers
    return params, proposed, []
