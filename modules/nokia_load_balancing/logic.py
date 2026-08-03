"""AMLE optimizer orchestration — Network Balance throughput + live CM extract."""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from core.cm_extractor.extraction import build_nokia_client
from core.cm_extractor.nokia_client import NokiaCmError
from core.cm_extractor.nokia_semantics import (
    build_mo_path,
    get_mo_class_catalog,
    query_selected_parameters,
)
from core.cm_extractor.site_catalog import resolve_nokia_netact_site_id, scope_dn_needles

from . import config
from .export import build_backup_xml, build_changes_xml
from .rules import (
    amlepr_identifiers_from_row,
    highest_lowest_layer,
    layer_from_lncel,
    lncels_for_sector_letter,
    missing_hl_direction_warnings,
    normalize_throughput,
    parse_dn_parts,
    parse_sector_id,
    propose_parameter_set,
    propose_value,
    qualifies_highest_lowest_pair,
    sector_id_from_row,
    target_layer_from_sector,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_logger = logging.getLogger(__name__)
_AMLEPR_VERSION_CACHE: str | None = None


def _preview_root(username: str, token: str | None = None) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (username or "unknown"))[:64]
    root = _PROJECT_ROOT / "uploads" / "nokia_load_balancing" / (safe or "unknown")
    if token:
        root = root / token
    return root


def _resolve_amlepr_version(client) -> str:
    global _AMLEPR_VERSION_CACHE
    import os

    env_version = os.environ.get("AMLEPR_MO_VERSION", "").strip()
    if env_version:
        return env_version
    if _AMLEPR_VERSION_CACHE:
        return _AMLEPR_VERSION_CACHE
    catalog = get_mo_class_catalog(client, scope_level="MRBTS")
    for item in catalog:
        mo_id = (item.get("id") or item.get("mo_class_id") or "").strip()
        if mo_id == config.AMLE_MO_CLASS:
            version = (item.get("version") or "").strip()
            if version:
                _AMLEPR_VERSION_CACHE = version
                return version
    raise ValueError(f"{config.AMLE_MO_CLASS} not found in NetAct MO catalog")


def _sheet_rows_to_dicts(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    headers = [str(h) for h in (sheet.get("headers") or [])]
    rows: list[dict[str, Any]] = []
    for row in sheet.get("rows") or []:
        item = {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}
        rows.append(item)
    return rows


def _build_amle_query_client():
    """Scoped AMLEPR queries only — shorter timeout, fewer retries."""
    client = build_nokia_client()
    client.timeout = min(int(getattr(client, "timeout", 180) or 180), config.AMLE_CM_TIMEOUT_SEC)
    client.max_retries = min(int(getattr(client, "max_retries", 8) or 8), config.AMLE_CM_MAX_RETRIES)
    return client


def _build_amle_client(*, extended_timeout: bool = False):
    """Nokia CM client; multi-site pulls may use a longer timeout."""
    client = build_nokia_client()
    if extended_timeout:
        client.timeout = max(int(getattr(client, "timeout", 180) or 180), config.BULK_CM_TIMEOUT_SEC)
    return client


def _amle_selection(version: str) -> dict[str, Any]:
    return {
        "mo_class_id": config.AMLE_MO_CLASS,
        "version": version,
        "parameters": config.AMLE_PARAMS + config.CM_EXTRA_PARAMS,
    }


def _find_amlepr_sheet(workbook: dict[str, Any]) -> Any | None:
    for name, sheet in workbook.items():
        if "AMLEPR" in str(name).upper():
            return sheet
    return None


def _fetch_amle_rows_operations(site_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    One CM Operations Import_Export for all selected site ids (comma-separated DN scope).
    """
    from core.cm_extractor.config import build_nokia_operations_client, nokia_export_ssh_settings
    from core.cm_extractor.nokia_bulk_export import NokiaBulkExportError, run_controller_bulk_export
    from core.cm_extractor.nokia_excel_reimport import parse_nokia_workbook

    if not nokia_export_ssh_settings().get("configured"):
        raise NokiaBulkExportError("Nokia CM Operations SFTP is not configured (NOKIA_CM_SSH_* or NOKIA_PM_*).")

    client = _build_amle_client(extended_timeout=True)
    version = _resolve_amlepr_version(client)
    ops_client = build_nokia_operations_client()
    result = run_controller_bulk_export(
        client,
        ops_client,
        scope_level="MRBTS",
        site_ids=site_ids,
        selections=[_amle_selection(version)],
    )
    try:
        workbook = parse_nokia_workbook(result["excel_path"])
        sheet = _find_amlepr_sheet(workbook)
        if sheet is None:
            warnings = list(result.get("warnings") or [])
            warnings.append("AMLEPR sheet not found in CM Operations bulk export.")
            return [], warnings
        rows = list(sheet.rows.values())
        warnings = list(result.get("warnings") or [])
        warnings.append(
            f"AMLEPR: CM Operations bulk export for {len(site_ids)} site(s), {len(rows)} row(s)."
        )
        return rows, warnings
    finally:
        tmpdir = result.get("tmpdir")
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _query_amlepr_scoped(
    client,
    metadata_site_id: str,
) -> tuple[list[str], list[list[Any]], list[str]]:
    """
    Query AMLEPR for one site using scoped MO paths only.

    Never falls back to all-PLMN — that path can scan the entire network and take minutes.
    """
    adaptation, abbreviation = config.AMLE_MO_CLASS.split(":", 1)
    parameters = config.AMLE_PARAMS + config.CM_EXTRA_PARAMS
    warnings: list[str] = []
    netact_id = resolve_nokia_netact_site_id(metadata_site_id) or metadata_site_id
    path_ids = list(dict.fromkeys([netact_id, metadata_site_id]))

    headers: list[str] = []
    rows: list[list[Any]] = []
    used_path = ""
    for path_id in path_ids:
        mo_path = build_mo_path(
            adaptation,
            abbreviation,
            scope_level="MRBTS",
            element_id=path_id,
        )
        t0 = time.perf_counter()
        headers, rows = query_selected_parameters(
            client,
            mo_path,
            parameters,
            adaptation=adaptation,
            abbreviation=abbreviation,
            conf_id=1,
            site_id=metadata_site_id,
            scope_level="MRBTS",
        )
        elapsed = time.perf_counter() - t0
        used_path = path_id
        _logger.info(
            "AMLEPR scoped query site=%s path_id=%s rows=%d elapsed=%.2fs",
            metadata_site_id,
            path_id,
            len(rows),
            elapsed,
        )
        if rows:
            break

    if not rows:
        warnings.append(
            f"Site {metadata_site_id}: scoped AMLEPR query returned 0 rows "
            f"(tried NetAct path ids {', '.join(path_ids)})."
        )
        return headers, rows, warnings

    dn_index = headers.index("DN") if "DN" in headers else 0
    needles = scope_dn_needles(metadata_site_id, "MRBTS")
    if needles:
        filtered = [row for row in rows if any(needle in str(row[dn_index]) for needle in needles)]
        if filtered:
            rows = filtered
        elif rows:
            warnings.append(
                f"Site {metadata_site_id}: {len(rows)} AMLEPR row(s) from path {used_path} "
                "did not match site DN filters."
            )

    return headers, rows, warnings


def _fetch_amle_rows_open_api_site(site_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    client = _build_amle_query_client()
    headers, rows, warnings = _query_amlepr_scoped(client, site_id)
    if not rows:
        return [], warnings
    return _sheet_rows_to_dicts({"headers": headers, "rows": rows}), warnings


def _fetch_amle_rows_open_api(
    site_ids: list[str],
    *,
    prior_warnings: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Scoped Open API queries per site — never all-PLMN."""
    warnings = list(prior_warnings or [])
    site_ids = [sid for sid in dict.fromkeys(site_ids) if sid]
    if not site_ids:
        return [], warnings

    t0 = time.perf_counter()

    if len(site_ids) == 1:
        rows, site_warnings = _fetch_amle_rows_open_api_site(site_ids[0])
        warnings.extend(site_warnings)
        warnings.append(f"AMLEPR fetch: 1 site in {time.perf_counter() - t0:.1f}s")
        return rows, warnings

    workers = min(config.OPEN_API_PARALLEL_WORKERS, len(site_ids))
    all_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_amle_rows_open_api_site, site_id): site_id
            for site_id in site_ids
        }
        for future in as_completed(futures):
            site_id = futures[future]
            try:
                rows, site_warnings = future.result()
            except Exception as exc:
                warnings.append(f"Site {site_id}: CM extract failed ({exc})")
                continue
            all_rows.extend(rows)
            warnings.extend(site_warnings)

    warnings.insert(
        0,
        f"AMLEPR: {len(site_ids)} site(s) via scoped Open API in {time.perf_counter() - t0:.1f}s "
        f"({workers} workers).",
    )
    return all_rows, warnings


def _fetch_amle_rows(site_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    site_ids = [sid for sid in dict.fromkeys(site_ids) if sid]
    if not site_ids:
        return [], []

    # AMLEPR is 4 parameters on a small MO — CM Operations Import_Export (RAML/SFTP)
    # is built for heavy MO dumps (LNREL, etc.) and is usually much slower than
    # parallel scoped Open API queries. Opt in via AMLE_USE_CM_OPERATIONS_BULK=1.
    if config.AMLE_USE_CM_OPERATIONS_BULK:
        from core.cm_extractor.config import nokia_export_ssh_settings

        if nokia_export_ssh_settings().get("configured"):
            try:
                return _fetch_amle_rows_operations(site_ids)
            except Exception as exc:
                return _fetch_amle_rows_open_api(
                    site_ids,
                    prior_warnings=[f"CM Operations bulk export failed ({exc}); using Open API per site."],
                )

    return _fetch_amle_rows_open_api(site_ids)


def _parse_sector_inputs(sectors: list[dict[str, Any]]) -> tuple[dict[str, dict], list[str], list[str]]:
    """
    Returns (sector_map, mrbts_ids, errors).

    sector_map: {sector_id: {throughput, highest, lowest, mrbts, letter}}
    """
    sector_map: dict[str, dict] = {}
    errors: list[str] = []
    mrbts_ids: set[str] = set()

    for idx, item in enumerate(sectors or []):
        sector_id = str(item.get("sector_id") or item.get("sector") or "").strip()
        if not sector_id:
            errors.append(f"Row {idx + 1}: missing sector_id")
            continue
        try:
            mrbts, letter = parse_sector_id(sector_id)
        except ValueError as exc:
            errors.append(f"Row {idx + 1}: {exc}")
            continue

        throughput = normalize_throughput(item.get("throughput") or item)
        highest, lowest = highest_lowest_layer(throughput)
        if not highest or not lowest:
            errors.append(
                f"Sector {sector_id}: need at least {config.MIN_ACTIVE_LAYERS} layers with throughput > 0"
            )
            continue

        sector_map[f"{mrbts}_{letter}"] = {
            "sector_id": f"{mrbts}_{letter}",
            "mrbts": mrbts,
            "letter": letter,
            "throughput": throughput,
            "highest_layer": highest,
            "lowest_layer": lowest,
        }
        mrbts_ids.add(mrbts)

    return sector_map, sorted(mrbts_ids), errors


def analyze_sectors(sectors: list[dict[str, Any]]) -> dict[str, Any]:
    sector_map, site_ids, input_errors = _parse_sector_inputs(sectors)
    if not sector_map:
        return {
            "success": False,
            "errors": input_errors or ["No valid sectors with throughput data"],
            "rows": [],
            "changes": [],
            "warnings": [],
        }

    try:
        amle_rows, cm_warnings = _fetch_amle_rows(site_ids)
    except NokiaCmError as exc:
        return {
            "success": False,
            "errors": [str(exc)],
            "rows": [],
            "changes": [],
            "warnings": input_errors,
        }
    except Exception as exc:
        return {
            "success": False,
            "errors": [f"CM extract failed: {exc}"],
            "rows": [],
            "changes": [],
            "warnings": input_errors,
        }

    proposals: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    skipped: list[str] = []
    warnings = list(input_errors) + list(cm_warnings)
    sectors_with_amle: set[str] = set()
    sectors_with_hl_pair: set[str] = set()
    hl_directions: dict[str, set[tuple[str, str]]] = {}
    sectors_clamped_rows: dict[str, int] = {}

    for row in amle_rows:
        dn = str(row.get("DN") or row.get("distName") or "").strip()
        if not dn:
            continue

        sid = sector_id_from_row(row)
        if not sid:
            continue
        sid_norm = sid.upper().replace("-", "_")
        sector_info = sector_map.get(sid_norm)
        if not sector_info:
            continue

        sectors_with_amle.add(sid_norm)

        _, lncel_str = parse_dn_parts(dn)
        if not lncel_str and row.get("LNCEL") is not None:
            lncel_str = str(row.get("LNCEL")).strip()
        if not lncel_str:
            continue
        try:
            src_layer = layer_from_lncel(int(lncel_str))
        except ValueError:
            src_layer = "Other"

        sector_lncels = lncels_for_sector_letter(sector_info["letter"])
        tgt_layer = target_layer_from_sector(sector_lncels, row.get("targetCarrierFreq"))
        highest = sector_info["highest_layer"]
        lowest = sector_info["lowest_layer"]
        qualifies, is_highest_source = qualifies_highest_lowest_pair(
            src_layer,
            tgt_layer,
            highest,
            lowest,
        )
        if not qualifies:
            continue

        sectors_with_hl_pair.add(sid_norm)
        hl_directions.setdefault(sid_norm, set()).add((src_layer, tgt_layer))
        is_highest = is_highest_source
        is_lowest = not is_highest_source

        action = "Reduce aggressiveness" if is_highest else "Increase aggressiveness"
        ids = amlepr_identifiers_from_row(row, dn)
        rec: dict[str, Any] = {
            "sector_id": sid_norm,
            "dn": dn,
            "mrbts": sector_info["mrbts"],
            "netact_mrbts": ids.get("mrbts"),
            "lnbts": ids.get("lnbts"),
            "lncel": ids.get("lncel") or lncel_str,
            "amlepr": ids.get("amlepr"),
            "source_layer": src_layer,
            "target_layer": tgt_layer,
            "target_carrier_freq": row.get("targetCarrierFreq"),
            "highest_layer": highest,
            "lowest_layer": lowest,
            "action": action,
            "parameters": {},
            "current_values": {},
            "proposed_values": {},
        }

        for param in config.AMLE_PARAMS + config.CM_EXTRA_PARAMS:
            if param in row:
                rec["current_values"][param] = row.get(param)

        row_changes = 0
        parameters, param_proposed, blockers = propose_parameter_set(
            row,
            is_highest=is_highest,
            is_lowest=is_lowest,
        )
        rec["proposed_values"].update(param_proposed)
        rec["parameters"] = parameters

        for param, vals in parameters.items():
            changes.append({
                "mo_class": config.AMLE_MO_CLASS,
                "target": dn,
                "parameter": param,
                "new_value": _format_cm_value(vals["proposed"]),
                "old_value": _format_cm_value(vals["current"]),
            })
            row_changes += 1

        rec["proposed_values"]["targetCarrierFreq"] = rec["current_values"].get("targetCarrierFreq")
        review_rows.append(rec)

        if row_changes == len(config.AMLE_PARAMS):
            proposals.append(rec)
        elif blockers:
            sectors_clamped_rows[sid_norm] = sectors_clamped_rows.get(sid_norm, 0) + 1
            skipped.append(f"{sid_norm} {dn}: already at 0/100 limits — {'; '.join(blockers)}")
        else:
            skipped.append(f"{sid_norm} {dn}: no parameter change required")

    for sid, info in sector_map.items():
        present = hl_directions.get(sid, set())
        if present:
            warnings.extend(
                missing_hl_direction_warnings(
                    sid,
                    info["highest_layer"],
                    info["lowest_layer"],
                    present,
                )
            )

    matched_sectors = {p["sector_id"] for p in proposals}
    sectors_at_limits = sorted(s for s in sectors_with_hl_pair if s not in matched_sectors)

    summary = {
        "sectors_requested": len(sector_map),
        "sectors_with_proposals": len(matched_sectors),
        "sectors_at_limits": len(sectors_at_limits),
        "hl_review_rows": len(review_rows),
        "hl_rows_proposed": len(proposals),
        "hl_rows_skipped_clamped": len(skipped),
        "parameter_changes": len(changes),
    }

    warnings.insert(
        0,
        "Summary: "
        f"{summary['hl_rows_proposed']} AMLEPR row(s) ready to export (all 3 params change); "
        f"{summary['hl_rows_skipped_clamped']} row(s) skipped — values already at 0 or 100; "
        f"{summary['sectors_with_proposals']}/{summary['sectors_requested']} sector(s) have exportable changes.",
    )

    if skipped:
        warnings.extend(skipped[:5])
        if len(skipped) > 5:
            warnings.append(f"… and {len(skipped) - 5} more rows at limits (see Excel review sheet)")

    for sid, info in sector_map.items():
        if sid in matched_sectors:
            continue
        if sid not in sectors_with_amle:
            warnings.append(f"Sector {sid}: no AMLE rows found in CM extract (check site id mapping)")
        elif sid not in sectors_with_hl_pair:
            warnings.append(
                f"Sector {sid}: AMLE rows found but no highest↔lowest co-sector pair "
                f"({info['highest_layer']}↔{info['lowest_layer']}) in AMLEPR"
            )
        else:
            clamped_n = sectors_clamped_rows.get(sid, 0)
            warnings.append(
                f"Sector {sid}: HL pair ({info['highest_layer']}↔{info['lowest_layer']}) found "
                f"but no export — {clamped_n or 'all'} AMLEPR row(s) already at 0/100 limits "
                f"(±10 would not move all 3 parameters)"
            )

    return {
        "success": True,
        "errors": input_errors,
        "rows": proposals,
        "review_rows": review_rows,
        "changes": changes,
        "warnings": warnings,
        "summary": summary,
        "site_ids": site_ids,
        "amle_row_count": len(amle_rows),
        "change_count": len(changes),
        "review_row_count": len(review_rows),
    }


def _format_cm_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


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


def preview_xml(username: str, token: str) -> str:
    preview = load_preview(username, token)
    changes = preview.get("changes") or []
    if not changes:
        raise ValueError("No parameter changes in preview.")
    return build_changes_xml(changes, plan_name=f"PrimeNet_NokiaLB_{token[:8]}")


def preview_backup_xml(username: str, token: str) -> str:
    preview = load_preview(username, token)
    changes = preview.get("changes") or []
    if not changes:
        raise ValueError("No parameter changes in preview.")
    return build_backup_xml(changes, plan_name=f"PrimeNet_NokiaLB_backup_{token[:8]}")


def write_preview_xml(username: str, token: str, xml_text: str) -> str:
    dest = _preview_root(username, token)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "oss_plan.xml"
    path.write_text(xml_text, encoding="utf-8")
    return str(path)
