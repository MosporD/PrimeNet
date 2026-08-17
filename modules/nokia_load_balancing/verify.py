"""Readiness checks for Nokia Load Balancing: ingest → analyze → XML → OSS config.

Live NetAct import is not executed here. XML generation and configuration
are proven; OSS push stays behind the existing confirmation phrase.
"""

from __future__ import annotations

from typing import Any

from core.cm_extractor.config import nokia_configured, nokia_export_ssh_settings

from . import config
from .balance_data import balance_configured
from .balance_store import snapshot_inventory
from .export import build_backup_xml, build_changes_xml
from .rules import propose_parameter_set


_SAMPLE_CHANGES = [
    {
        "mo_class": "NOKLTE:AMLEPR",
        "dist_name": "PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1/AMLEPR-1",
        "parameter": "cacHeadroom",
        "new_value": "40",
        "old_value": "50",
    },
    {
        "mo_class": "NOKLTE:AMLEPR",
        "dist_name": "PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1/AMLEPR-1",
        "parameter": "deltaCac",
        "new_value": "40",
        "old_value": "50",
    },
    {
        "mo_class": "NOKLTE:AMLEPR",
        "dist_name": "PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1/AMLEPR-1",
        "parameter": "maxCacThreshold",
        "new_value": "60",
        "old_value": "50",
    },
]


def _check(name: str, ok: bool, detail: str, *, blocking: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "blocking": bool(blocking),
        "detail": detail,
        "status": "ok" if ok else ("error" if blocking else "warn"),
    }


def _run_rule_self_test() -> tuple[bool, str]:
    row = {"cacHeadroom": 50, "deltaCac": 50, "maxCacThreshold": 50}
    params, _, blockers = propose_parameter_set(row, is_highest=False, is_lowest=True)
    if blockers or params.get("cacHeadroom", {}).get("proposed") != 40:
        return False, f"Lowest-layer proposal failed: {blockers or params}"
    params, _, blockers = propose_parameter_set(row, is_highest=True, is_lowest=False)
    if blockers or params.get("maxCacThreshold", {}).get("proposed") != 40:
        return False, f"Highest-layer proposal failed: {blockers or params}"
    return True, "AMLE rule engine: lowest offloads more, highest offloads less."


def _xml_dry_run() -> tuple[bool, str]:
    xml_text = build_changes_xml(_SAMPLE_CHANGES, plan_name="PrimeNet_NokiaLB_verify")
    backup = build_backup_xml(_SAMPLE_CHANGES, plan_name="PrimeNet_NokiaLB_verify_backup")
    needed = ("raml", "NOKLTE:AMLEPR", "cacHeadroom", "40", "managedObject")
    missing = [token for token in needed if token not in xml_text]
    if missing:
        return False, f"RAML dry-run missing {missing}"
    if "50" not in backup:
        return False, "Backup XML did not keep current values."
    return True, f"RAML plan XML generated ({len(xml_text)} chars) with backup plan."


def verify_pipeline() -> dict[str, Any]:
    """Return a structured readiness report for the AMLE write path."""
    inventory = snapshot_inventory()
    nokia_snaps = 0
    vendor_rows = inventory.get("vendors") if isinstance(inventory, dict) else []
    for item in vendor_rows or []:
        if str(item.get("vendor") or "").lower() == "nokia":
            nokia_snaps = int(item.get("snapshot_count") or 0)
            break

    ssh = nokia_export_ssh_settings()
    ssh_ok = bool(ssh.get("configured"))
    cm_ok = bool(nokia_configured())
    balance_ok = bool(balance_configured())
    rules_ok, rules_detail = _run_rule_self_test()
    xml_ok, xml_detail = _xml_dry_run()

    sqlite_ok = nokia_snaps > 0
    sqlite_detail = (
        f"Nokia Network Balance snapshots in SQLite: {nokia_snaps}."
        if sqlite_ok
        else "No Nokia Network Balance snapshot in SQLite. Sync the share first."
    )

    checks = [
        _check("network_balance_share", balance_ok, "Network Balance path is reachable." if balance_ok else "Network Balance share is not configured or unreachable."),
        _check("sqlite_snapshots", sqlite_ok, sqlite_detail),
        _check("amle_rules", rules_ok, rules_detail),
        _check("raml_xml_dry_run", xml_ok, xml_detail),
        _check(
            "nokia_cm",
            cm_ok,
            "Nokia CM client settings present." if cm_ok else "Nokia CM is not configured (NOKIA_CM_*). Analyze needs live AMLEPR.",
        ),
        _check(
            "oss_ssh",
            ssh_ok,
            "OSS SSH / reimport path configured." if ssh_ok else "OSS push is not configured (NOKIA_CM_SSH_*). XML download still works.",
            blocking=False,
        ),
    ]

    blocking_failed = [c for c in checks if c["blocking"] and not c["ok"]]
    ready_for_analyze = sqlite_ok and rules_ok and cm_ok
    ready_for_xml = ready_for_analyze and xml_ok
    ready_for_oss = ready_for_xml and ssh_ok and cm_ok

    return {
        "success": not blocking_failed,
        "ready_for_analyze": ready_for_analyze,
        "ready_for_xml": ready_for_xml,
        "ready_for_oss_push": ready_for_oss,
        "live_oss_push_attempted": False,
        "note": (
            "Pipeline verified through RAML XML generation. Live NetAct actualImport "
            "is not executed by this check — use Apply on a reviewed preview."
        ),
        "checks": checks,
        "inventory": inventory,
        "amle_mo_class": config.AMLE_MO_CLASS,
        "amle_params": list(config.AMLE_PARAMS),
    }
