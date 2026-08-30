"""Pre-flight checks for Nokia RAML CM plans (XML parser / XML generator)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.radio import cm_store
from utils.xml_safety import parse_xml_file

_RANGE_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:to|–|-|\.\.)\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_OPS = frozenset({"create", "update", "delete"})
_FINDING_CAP = 120

_spec_index: dict[tuple[str, str], dict[str, str]] | None = None
_mo_leaves: set[str] | None = None


def _local(tag: str) -> str:
    return (tag or "").split("}")[-1]


def _mo_leaf(name: str) -> str:
    return (name or "").split("/")[-1].strip()


def _param_specs() -> tuple[dict[tuple[str, str], dict[str, str]], set[str]]:
    global _spec_index, _mo_leaves
    if _spec_index is not None and _mo_leaves is not None:
        return _spec_index, _mo_leaves
    from modules.parameter_dictionary.nokia_loader import load_nokia_data

    data = load_nokia_data()
    index: dict[tuple[str, str], dict[str, str]] = {}
    leaves: set[str] = set()
    for mo_name, mo_info in (data.get("mos") or {}).items():
        leaf = (_mo_leaf(str(mo_info.get("leaf") or mo_name))).lower()
        if leaf:
            leaves.add(leaf)
        for row in mo_info.get("parameters") or []:
            abbrev = str(row.get("Abbreviated Name") or "").strip().lower()
            if not abbrev:
                continue
            spec = {k: str(v or "") for k, v in row.items()}
            index[(leaf, abbrev)] = spec
            index[(_mo_leaf(mo_name).lower(), abbrev)] = spec
    _spec_index = index
    _mo_leaves = leaves
    return index, leaves


def _value_in_range(value: str, range_text: str) -> bool:
    if not range_text or value in (None, ""):
        return True
    match = _RANGE_RE.search(range_text)
    if not match:
        return True
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return True
    return float(match.group(1)) <= number <= float(match.group(2))


def _iter_managed_objects(root) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for elem in root.iter():
        if _local(elem.tag) != "managedObject":
            continue
        params: list[tuple[str, str]] = []
        for child in list(elem):
            local = _local(child.tag)
            if local == "p":
                name = str(child.get("name") or "").strip()
                if name:
                    params.append((name, (child.text or "").strip()))
            elif local == "list":
                list_name = str(child.get("name") or "").strip()
                if list_name:
                    params.append((list_name, "<list>"))
        objects.append({
            "class": str(elem.get("class") or "").strip(),
            "dist_name": str(elem.get("distName") or elem.get("distname") or "").strip(),
            "operation": str(elem.get("operation") or "").strip().lower(),
            "params": params,
        })
    return objects


def _schema_findings(root) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    local_root = _local(root.tag)
    if local_root not in {"raml", "cmData", "managedObject"}:
        findings.append({
            "severity": "warning",
            "code": "unknown_root",
            "message": f"Root element is <{local_root}>, not a Nokia RAML plan.",
            "mo_class": "",
            "parameter": "",
            "dist_name": "",
        })
    has_cm = local_root == "cmData" or any(_local(el.tag) == "cmData" for el in root)
    has_mo = any(_local(el.tag) == "managedObject" for el in root.iter())
    if not has_cm and has_mo:
        findings.append({
            "severity": "warning",
            "code": "missing_cmdata",
            "message": "Plan has managed objects but no <cmData> wrapper.",
            "mo_class": "",
            "parameter": "",
            "dist_name": "",
        })
    if not has_mo:
        findings.append({
            "severity": "error",
            "code": "no_managed_objects",
            "message": "No <managedObject> elements found — this file is not a CM plan.",
            "mo_class": "",
            "parameter": "",
            "dist_name": "",
        })
    return findings


def _rule_matches(rule: dict[str, Any], mo_class: str, parameter: str) -> bool:
    if str(rule.get("parameter") or "").strip().lower() != parameter.lower():
        return False
    rule_mo = str(rule.get("mo_class") or "").strip()
    if rule_mo and _mo_leaf(rule_mo).lower() != _mo_leaf(mo_class).lower():
        return False
    return True


def _apply_rule(rule: dict[str, Any], value: str) -> bool:
    kind = str(rule.get("rule_type") or "")
    if kind == "not_empty":
        return not str(value or "").strip()
    if kind == "equals":
        return str(value) != str(rule.get("expected_value"))
    if kind == "range":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return True
        lo = rule.get("min_value")
        hi = rule.get("max_value")
        if lo is not None and number < float(lo):
            return True
        if hi is not None and number > float(hi):
            return True
        return False
    return False


def _snapshot_map(limit: int = 40000) -> dict[tuple[str, str, str], str]:
    out: dict[tuple[str, str, str], str] = {}
    try:
        rows = cm_store.latest_snapshot_rows(limit=limit)
    except Exception:
        return out
    for row in rows:
        key = (
            _mo_leaf(str(row.get("mo_class") or "")).lower(),
            str(row.get("dn") or "").strip().lower(),
            str(row.get("parameter") or "").strip().lower(),
        )
        out[key] = str(row.get("value") if row.get("value") is not None else "")
    return out


def validate_raml_plan(xml_path: str, *, against_snapshot: bool = True) -> dict[str, Any]:
    """Return schema / dictionary / golden-rule / snapshot-diff findings for a RAML plan."""
    root = parse_xml_file(xml_path)
    findings = _schema_findings(root)
    objects = _iter_managed_objects(root)
    try:
        specs, known_mos = _param_specs()
    except Exception:
        specs, known_mos = {}, set()
    try:
        rules = cm_store.list_rules()
    except Exception:
        rules = []
    snapshots = _snapshot_map() if against_snapshot else {}

    dict_available = bool(specs)
    unknown_params = 0
    range_fails = 0
    rule_fails = 0
    diffs = 0

    for obj in objects:
        mo_class = obj["class"]
        dist_name = obj["dist_name"]
        operation = obj["operation"]
        leaf = _mo_leaf(mo_class).lower()

        if not mo_class:
            findings.append({
                "severity": "error",
                "code": "missing_class",
                "message": "managedObject is missing class.",
                "mo_class": "",
                "parameter": "",
                "dist_name": dist_name,
            })
            continue
        if not dist_name:
            findings.append({
                "severity": "error",
                "code": "missing_distname",
                "message": f"{mo_class} is missing distName.",
                "mo_class": mo_class,
                "parameter": "",
                "dist_name": "",
            })
        if operation and operation not in _OPS:
            findings.append({
                "severity": "warning",
                "code": "bad_operation",
                "message": f"{mo_class} has operation '{operation}' (expected create/update/delete).",
                "mo_class": mo_class,
                "parameter": "",
                "dist_name": dist_name,
            })
        if dict_available and leaf and leaf not in known_mos:
            findings.append({
                "severity": "warning",
                "code": "unknown_mo",
                "message": f"MO class {mo_class} is not in the Nokia parameter dictionary.",
                "mo_class": mo_class,
                "parameter": "",
                "dist_name": dist_name,
            })

        for param_name, value in obj["params"]:
            spec = specs.get((leaf, param_name.lower())) if dict_available else None
            if dict_available and leaf in known_mos and spec is None:
                unknown_params += 1
                if unknown_params <= _FINDING_CAP:
                    findings.append({
                        "severity": "warning",
                        "code": "unknown_parameter",
                        "message": f"{mo_class}.{param_name} is not in the Nokia dictionary for this MO.",
                        "mo_class": mo_class,
                        "parameter": param_name,
                        "dist_name": dist_name,
                    })
            if spec:
                required = str(spec.get("Required on Creation") or "").strip().lower()
                if operation == "create" and required in {"yes", "true", "1", "mandatory"} and not value:
                    findings.append({
                        "severity": "error",
                        "code": "required_missing",
                        "message": f"{mo_class}.{param_name} is required on creation but empty.",
                        "mo_class": mo_class,
                        "parameter": param_name,
                        "dist_name": dist_name,
                    })
                range_text = spec.get("Range and step") or ""
                if value and value != "<list>" and not _value_in_range(value, range_text):
                    range_fails += 1
                    if range_fails <= _FINDING_CAP:
                        findings.append({
                            "severity": "error",
                            "code": "range",
                            "message": f"{mo_class}.{param_name}={value} is outside {range_text}.",
                            "mo_class": mo_class,
                            "parameter": param_name,
                            "dist_name": dist_name,
                        })

            for rule in rules:
                if not _rule_matches(rule, mo_class, param_name):
                    continue
                if not _apply_rule(rule, value):
                    continue
                rule_fails += 1
                if rule_fails <= _FINDING_CAP:
                    findings.append({
                        "severity": "error",
                        "code": "golden_rule",
                        "message": str(rule.get("description") or f"{param_name} fails golden rule {rule.get('id')}."),
                        "mo_class": mo_class,
                        "parameter": param_name,
                        "dist_name": dist_name,
                    })

            if snapshots and dist_name:
                current = snapshots.get((leaf, dist_name.lower(), param_name.lower()))
                if current is not None and str(current) != str(value):
                    diffs += 1
                    if diffs <= _FINDING_CAP:
                        findings.append({
                            "severity": "info",
                            "code": "diff",
                            "message": f"{mo_class}.{param_name}: network={current} → plan={value}",
                            "mo_class": mo_class,
                            "parameter": param_name,
                            "dist_name": dist_name,
                        })

        if len(findings) >= _FINDING_CAP * 3:
            break

    codes = Counter(item["code"] for item in findings)
    return {
        "success": True,
        "mo_count": len(objects),
        "param_count": sum(len(obj["params"]) for obj in objects),
        "dictionary_available": dict_available,
        "snapshot_available": bool(snapshots),
        "summary": {
            "errors": sum(1 for item in findings if item["severity"] == "error"),
            "warnings": sum(1 for item in findings if item["severity"] == "warning"),
            "diffs": sum(1 for item in findings if item["code"] == "diff"),
            "codes": dict(codes),
        },
        "findings": findings[: _FINDING_CAP * 3],
        "capped": len(findings) >= _FINDING_CAP * 3,
    }
