"""Huawei Load Balancing orchestration — Network Balance throughput + CellMLB proposals.

Live U2020 CellMLB extract is optional. Proposals always run from Network Balance
highest/lowest layers; current values default to HedEx CellMLB typicals when CM
is not configured. OSS push is intentionally not wired — export MML/Excel only
until the Nokia AMLE write path is trusted in production.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.nokia_load_balancing.rules import highest_lowest_layer, parse_sector_id

from . import config
from .export import build_mml, build_review_excel
from .rules import propose_parameter_set

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _preview_root(username: str, token: str | None = None) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (username or "unknown"))[:64]
    root = _PROJECT_ROOT / "uploads" / "huawei_load_balancing" / (safe or "unknown")
    if token:
        root = root / token
    return root


def analyze_sectors(sectors: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []

    for item in sectors:
        sector_id = str(item.get("sector_id") or "").strip()
        if not sector_id:
            continue
        try:
            site_id, letter = parse_sector_id(sector_id)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        throughput = item.get("throughput") or {}
        highest, lowest = highest_lowest_layer(throughput)
        if not highest or not lowest or highest == lowest:
            warnings.append(f"Sector {sector_id}: need two layers with different throughput.")
            continue

        for layer, is_highest, is_lowest in (
            (highest, True, False),
            (lowest, False, True),
        ):
            params, _proposed, blockers = propose_parameter_set(
                None,
                is_highest=is_highest,
                is_lowest=is_lowest,
            )
            role = "highest" if is_highest else "lowest"
            if blockers:
                warnings.append(f"Sector {sector_id} {layer} ({role}): {'; '.join(blockers)}")
                continue
            current_values = {name: config.DEFAULTS[name] for name in config.CELLMLB_PARAMS}
            proposed_values = {name: spec["proposed"] for name, spec in params.items()}
            review_rows.append({
                "sector_id": sector_id,
                "site_id": site_id,
                "letter": letter,
                "layer": layer,
                "role": role,
                "mo_class": config.CELLMLB_MO,
                "current_values": current_values,
                "proposed_values": proposed_values,
                "throughput": throughput.get(layer),
            })
            for name, spec in params.items():
                change = {
                    "sector_id": sector_id,
                    "site_id": site_id,
                    "letter": letter,
                    "layer": layer,
                    "role": role,
                    "mo_class": config.CELLMLB_MO,
                    "parameter": name,
                    "old_value": spec["current"],
                    "new_value": spec["proposed"],
                    "delta": spec["delta"],
                }
                changes.append(change)
                rows.append({
                    "sector_id": sector_id,
                    "source": layer,
                    "target": lowest if is_highest else highest,
                    "action": "more aggressive MLB" if is_highest else "less aggressive MLB",
                    "parameter": name,
                    "current": spec["current"],
                    "proposed": spec["proposed"],
                    "delta": spec["delta"],
                })

    return {
        "success": bool(changes),
        "errors": errors if not changes else errors,
        "rows": rows,
        "review_rows": review_rows,
        "changes": changes,
        "warnings": warnings + [
            "Current CellMLB values are HedEx defaults — live U2020 extract is not required for this proposal.",
            "OSS push is disabled on Huawei until Nokia AMLE apply is trusted. Download MML/Excel and review on U2020.",
        ],
        "summary": {
            "sectors_requested": len(sectors),
            "sectors_with_proposals": len({r.get("sector_id") for r in review_rows}),
            "hl_rows_proposed": len(review_rows),
        },
        "change_count": len(changes),
        "review_row_count": len(review_rows),
        "site_ids": sorted({str(r.get("site_id") or "") for r in review_rows if r.get("site_id")}),
    }


def save_preview(username: str, payload: dict[str, Any]) -> str:
    token = uuid.uuid4().hex
    dest = _preview_root(username, token)
    dest.mkdir(parents=True, exist_ok=True)
    out = {
        "token": token,
        "username": username,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    (dest / "preview.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return token


def load_preview(username: str, token: str) -> dict[str, Any]:
    path = _preview_root(username, token) / "preview.json"
    if not path.is_file():
        raise FileNotFoundError("Preview not found or expired.")
    return json.loads(path.read_text(encoding="utf-8"))


def preview_excel(username: str, token: str) -> bytes:
    preview = load_preview(username, token)
    review_rows = preview.get("review_rows") or []
    if not review_rows:
        raise ValueError("No CellMLB review rows in preview.")
    return build_review_excel(review_rows, config_gaps=preview.get("warnings") or [])


def preview_mml(username: str, token: str) -> str:
    preview = load_preview(username, token)
    changes = preview.get("changes") or []
    if not changes:
        raise ValueError("No parameter changes in preview.")
    return build_mml(changes)
