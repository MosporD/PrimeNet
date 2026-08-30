"""Load Nokia parameter dictionary from Excel (with JSON cache)."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

_DIR = os.path.dirname(__file__)
NOKIA_PARAMS_DIR = os.path.join(_DIR, "Nokia Parameters")
NOKIA_EXCEL_PATH = os.path.join(NOKIA_PARAMS_DIR, "Nokia Parameter Description.xlsx")
RNC_BSC_EXCEL_PATH = os.path.join(NOKIA_PARAMS_DIR, "RNC & BSC Parameters.xlsx")
NOKIA_CACHE_PATH = os.path.join(_DIR, "data", "nokia_parameters.json")
NOKIA_INDEX_PATH = os.path.join(_DIR, "data", "nokia_parameters_index.json")
RNC_BSC_SHEETS = ("RNC", "BSC")

EXCEL_COLUMNS = [
    "Technology",
    "Abbreviated Name",
    "MO Class",
    "Min instance",
    "Max instance",
    "Parameter Category",
    "Parent Structure",
    "Child Parameters",
    "Full Name",
    "3GPP Name",
    "Data Type",
    "Units",
    "Multiplicity",
    "Description",
    "Range and step",
    "Formula for Getting Internal Value",
    "Default Value",
    "Default Value Notes",
    "Special Value",
    "Special Value Notes",
    "Related Functions",
    "Modification",
    "Required on Creation",
    "Related Parameters",
    "Parameter Relationships",
    "Features",
    "Interfaces",
    "3GPP References",
]

_cache: dict[str, Any] | None = None
_index_cache: dict[str, Any] | None = None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _nokia_excel_paths() -> list[str]:
    paths: list[str] = []
    if os.path.isdir(NOKIA_PARAMS_DIR):
        for name in sorted(os.listdir(NOKIA_PARAMS_DIR)):
            if name.lower().endswith((".xlsx", ".xls")):
                paths.append(os.path.join(NOKIA_PARAMS_DIR, name))
    return paths


def _excel_mtime() -> float:
    latest = 0.0
    for path in _nokia_excel_paths():
        try:
            latest = max(latest, os.path.getmtime(path))
        except OSError:
            continue
    return latest


def _cache_mtime() -> float:
    try:
        return os.path.getmtime(NOKIA_CACHE_PATH)
    except OSError:
        return 0.0


def _row_from_map(row_map: dict[str, Any]) -> dict[str, str]:
    fields = {str(col): _clean(row_map.get(col)) for col in row_map}
    if fields.get("Related Features") and not fields.get("Features"):
        fields["Features"] = fields["Related Features"]
    return fields


def _row_content_key(fields: dict[str, str]) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Fingerprint for deduplicating identical rows across RNC/BSC sheets."""
    mo = fields.get("MO Class") or ""
    param = fields.get("Abbreviated Name") or ""
    payload = tuple(
        sorted((key, value) for key, value in fields.items() if key != "Technology" and value)
    )
    return mo, param, payload


def _ingest_parameter_row(
    fields: dict[str, str],
    *,
    mos: dict[str, dict[str, Any]],
    param_descriptions: dict[str, str],
    param_to_mos: dict[str, list[str]],
    all_rows: list[dict[str, str]],
    seen_content: set[tuple[str, str, tuple[tuple[str, str], ...]]],
    all_columns: set[str],
) -> bool:
    mo = fields.get("MO Class") or ""
    param = fields.get("Abbreviated Name") or ""
    if not mo or not param:
        return False

    content_key = _row_content_key(fields)
    if content_key in seen_content:
        return False
    seen_content.add(content_key)

    all_columns.update(fields)
    all_rows.append(fields)
    technology = fields.get("Technology") or ""
    category = fields.get("Parameter Category") or "Other"

    entry = mos.setdefault(mo, {
        "technology": technology,
        "category": category,
        "leaf": mo.split("/")[-1],
        "parameters": [],
    })
    if technology and not entry.get("technology"):
        entry["technology"] = technology
    entry["parameters"].append(fields)

    description = fields.get("Description") or ""
    if description:
        existing = param_descriptions.get(param)
        if not existing or len(description) > len(existing):
            param_descriptions[param] = description

    param_to_mos.setdefault(param, [])
    if mo not in param_to_mos[param]:
        param_to_mos[param].append(mo)
    return True


def _ordered_columns(all_columns: set[str]) -> list[str]:
    ordered = [col for col in EXCEL_COLUMNS if col in all_columns]
    extras = sorted(col for col in all_columns if col not in EXCEL_COLUMNS)
    return ordered + extras


def _ingest_primary_excel(
    path: str,
    *,
    mos: dict[str, dict[str, Any]],
    param_descriptions: dict[str, str],
    param_to_mos: dict[str, list[str]],
    all_rows: list[dict[str, str]],
    seen_content: set[tuple[str, str, tuple[tuple[str, str], ...]]],
    all_columns: set[str],
) -> int:
    if not os.path.isfile(path):
        return 0

    df = pd.read_excel(path, engine="openpyxl")
    all_columns.update(str(col) for col in df.columns)
    added = 0
    for row_map in df.to_dict(orient="records"):
        fields = _row_from_map(row_map)
        if _ingest_parameter_row(
            fields,
            mos=mos,
            param_descriptions=param_descriptions,
            param_to_mos=param_to_mos,
            all_rows=all_rows,
            seen_content=seen_content,
            all_columns=all_columns,
        ):
            added += 1
    return added


def _ingest_rnc_bsc_excel(
    path: str,
    *,
    mos: dict[str, dict[str, Any]],
    param_descriptions: dict[str, str],
    param_to_mos: dict[str, list[str]],
    all_rows: list[dict[str, str]],
    seen_content: set[tuple[str, str, tuple[tuple[str, str], ...]]],
    all_columns: set[str],
) -> tuple[int, list[str]]:
    if not os.path.isfile(path):
        return 0, []

    xl = pd.ExcelFile(path, engine="openpyxl")
    added = 0
    skipped_sheets: list[str] = []
    seen_sheet_frames: list[pd.DataFrame] = []

    for sheet in xl.sheet_names:
        if sheet.upper() not in {name.upper() for name in RNC_BSC_SHEETS}:
            continue

        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        if any(other.equals(df) for other in seen_sheet_frames):
            skipped_sheets.append(sheet)
            continue
        seen_sheet_frames.append(df)

        technology = sheet.upper()
        all_columns.update(str(col) for col in df.columns)
        sheet_added = 0
        for row_map in df.to_dict(orient="records"):
            fields = _row_from_map(row_map)
            fields["Technology"] = technology
            if _ingest_parameter_row(
                fields,
                mos=mos,
                param_descriptions=param_descriptions,
                param_to_mos=param_to_mos,
                all_rows=all_rows,
                seen_content=seen_content,
                all_columns=all_columns,
            ):
                sheet_added += 1
        added += sheet_added

    return added, skipped_sheets


def build_nokia_data_from_excel() -> dict[str, Any]:
    """Parse all Nokia parameter Excel files into API-ready structures."""
    sources = _nokia_excel_paths()
    if not sources:
        return {"columns": EXCEL_COLUMNS, "mos": {}, "meta": {"source": "missing", "row_count": 0}}

    mos: dict[str, dict[str, Any]] = {}
    param_descriptions: dict[str, str] = {}
    param_to_mos: dict[str, list[str]] = {}
    all_rows: list[dict[str, str]] = []
    seen_content: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    all_columns: set[str] = set()
    source_files: list[str] = []
    skipped_sheets: list[str] = []

    if os.path.isfile(NOKIA_EXCEL_PATH):
        _ingest_primary_excel(
            NOKIA_EXCEL_PATH,
            mos=mos,
            param_descriptions=param_descriptions,
            param_to_mos=param_to_mos,
            all_rows=all_rows,
            seen_content=seen_content,
            all_columns=all_columns,
        )
        source_files.append(os.path.basename(NOKIA_EXCEL_PATH))

    if os.path.isfile(RNC_BSC_EXCEL_PATH):
        _, skipped = _ingest_rnc_bsc_excel(
            RNC_BSC_EXCEL_PATH,
            mos=mos,
            param_descriptions=param_descriptions,
            param_to_mos=param_to_mos,
            all_rows=all_rows,
            seen_content=seen_content,
            all_columns=all_columns,
        )
        source_files.append(os.path.basename(RNC_BSC_EXCEL_PATH))
        skipped_sheets.extend(skipped)

    columns = _ordered_columns(all_columns) if all_columns else EXCEL_COLUMNS

    mo_index = []
    for mo_name, mo_data in mos.items():
        mo_data["parameter_count"] = len(mo_data["parameters"])
        mo_index.append({
            "mo": mo_name,
            "leaf": mo_data.get("leaf") or mo_name.split("/")[-1],
            "technology": mo_data.get("technology") or "",
            "category": mo_data.get("category") or "",
            "parameter_count": mo_data["parameter_count"],
        })
    mo_index.sort(key=lambda item: item["mo"])

    technologies = sorted({row.get("Technology") for row in all_rows if row.get("Technology")})
    categories = sorted({row.get("Parameter Category") for row in all_rows if row.get("Parameter Category")})

    meta: dict[str, Any] = {
        "source": ", ".join(source_files) if source_files else "missing",
        "sources": source_files,
        "source_mtime": _excel_mtime(),
        "row_count": len(all_rows),
        "mo_count": len(mos),
        "param_count": len(param_descriptions),
        "technologies": technologies,
        "categories": categories,
    }
    if skipped_sheets:
        meta["skipped_duplicate_sheets"] = skipped_sheets

    return {
        "columns": columns,
        "mos": mos,
        "mo_index": mo_index,
        "param_descriptions": param_descriptions,
        "param_to_mos": param_to_mos,
        "meta": meta,
    }


def write_nokia_index(data: dict[str, Any] | None = None) -> str:
    payload = data if data is not None else load_nokia_data()
    index = {
        "columns": payload.get("columns") or EXCEL_COLUMNS,
        "mo_index": payload.get("mo_index") or [],
        "meta": payload.get("meta") or {},
    }
    os.makedirs(os.path.dirname(NOKIA_INDEX_PATH), exist_ok=True)
    with open(NOKIA_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    global _index_cache
    _index_cache = index
    return NOKIA_INDEX_PATH


def write_nokia_cache(data: dict[str, Any] | None = None) -> str:
    """Write parsed Nokia data to JSON cache."""
    payload = data if data is not None else build_nokia_data_from_excel()
    os.makedirs(os.path.dirname(NOKIA_CACHE_PATH), exist_ok=True)
    with open(NOKIA_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    write_nokia_index(payload)
    return NOKIA_CACHE_PATH


def load_nokia_data(force_refresh: bool = False) -> dict[str, Any]:
    """Load Nokia dictionary data (cache preferred, rebuild if Excel is newer)."""
    global _cache
    excel_mtime = _excel_mtime()
    cache_stale = _cache_mtime() < excel_mtime

    if not force_refresh and _cache is not None and not cache_stale:
        return _cache

    if not force_refresh and os.path.isfile(NOKIA_CACHE_PATH) and not cache_stale:
        with open(NOKIA_CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
        return _cache

    _cache = build_nokia_data_from_excel()
    if _cache.get("mos"):
        write_nokia_cache(_cache)
    return _cache


def get_nokia_mos_payload() -> dict[str, Any]:
    """Return MO tree for /api/parameter-dictionary/list."""
    data = load_nokia_data()
    return data.get("mos") or {}


def get_nokia_index_payload() -> dict[str, Any]:
    """Lightweight payload: columns, MO index, meta (no parameter rows)."""
    global _index_cache
    excel_mtime = _excel_mtime()
    try:
        index_mtime = os.path.getmtime(NOKIA_INDEX_PATH)
    except OSError:
        index_mtime = 0.0
    index_stale = index_mtime < excel_mtime if excel_mtime else False

    if _index_cache is not None and not index_stale:
        return _index_cache

    if os.path.isfile(NOKIA_INDEX_PATH) and not index_stale:
        with open(NOKIA_INDEX_PATH, encoding="utf-8") as f:
            _index_cache = json.load(f)
        return _index_cache

    data = load_nokia_data()
    _index_cache = {
        "columns": data.get("columns") or EXCEL_COLUMNS,
        "mo_index": data.get("mo_index") or [],
        "meta": data.get("meta") or {},
    }
    if data.get("mo_index"):
        write_nokia_index(data)
    return _index_cache


def get_nokia_list_payload() -> dict[str, Any]:
    """Backward-compatible alias for index payload."""
    return get_nokia_index_payload()


def get_nokia_mo_parameters(mo_name: str) -> dict[str, Any]:
    """Return all Excel-column parameters for one MO class."""
    data = load_nokia_data()
    mo_info = (data.get("mos") or {}).get(mo_name)
    if not mo_info:
        return {"mo": mo_name, "parameters": [], "technology": "", "category": ""}
    return {
        "mo": mo_name,
        "technology": mo_info.get("technology") or "",
        "category": mo_info.get("category") or "",
        "leaf": mo_info.get("leaf") or mo_name.split("/")[-1],
        "parameter_count": len(mo_info.get("parameters") or []),
        "parameters": mo_info.get("parameters") or [],
    }


def lookup_parameter_row(mo_name: str, abbreviated_name: str) -> dict[str, str] | None:
    target = (abbreviated_name or "").strip().lower()
    if not target:
        return None
    payload = get_nokia_mo_parameters(mo_name)
    for row in payload.get("parameters") or []:
        if str(row.get("Abbreviated Name") or "").strip().lower() == target:
            return row
    leaf = mo_name.split("/")[-1].strip().lower()
    data = load_nokia_data()
    for name, info in (data.get("mos") or {}).items():
        if (info.get("leaf") or name.split("/")[-1]).strip().lower() != leaf:
            continue
        for row in info.get("parameters") or []:
            if str(row.get("Abbreviated Name") or "").strip().lower() == target:
                return row
    return None


def search_nokia_parameters(query: str, limit: int = 500) -> dict[str, Any]:
    """Search parameters across all MOs (server-side)."""
    data = load_nokia_data()
    columns = data.get("columns") or EXCEL_COLUMNS
    mos = data.get("mos") or {}
    term = (query or "").strip().lower()
    if len(term) < 2:
        return {"parameters": [], "total": 0, "capped": False}

    words = term.split()
    results: list[dict[str, str]] = []
    capped = False

    for mo_name, mo_info in mos.items():
        for row in mo_info.get("parameters") or []:
            blob = " ".join(str(row.get(col) or "") for col in columns).lower()
            if all(w in blob for w in words):
                results.append({**row, "_mo": mo_name})
                if len(results) >= limit:
                    capped = True
                    break
        if capped:
            break

    return {"parameters": results, "total": len(results), "capped": capped}


def _query_words(query: str) -> list[str]:
    _STOP = frozenset({
        "what", "does", "do", "the", "a", "an", "is", "are", "was", "were", "be",
        "which", "who", "where", "when", "why", "how", "related", "parameters",
        "parameter", "feature", "features", "about", "explain", "tell", "me",
        "for", "and", "or", "to", "of", "in", "on", "with", "from", "that", "this",
    })
    import re
    words = [w for w in re.split(r"\W+", (query or "").lower()) if len(w) >= 2]
    filtered = [w for w in words if w not in _STOP]
    return filtered or words


def _score_text(text: str, words: list[str]) -> int:
    if not words:
        return 0
    lower = (text or "").lower()
    score = 0
    for word in words:
        if word in lower:
            score += 3
        elif any(word in part for part in lower.split()):
            score += 1
    return score


def _truncate(text: str, limit: int = 480) -> str:
    import re
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def search_nokia_entries(query: str, limit: int = 15) -> list[dict[str, Any]]:
    data = load_nokia_data()
    mos = data.get("mos") or {}
    words = _query_words(query)
    if not words:
        return []

    query_lower = query.lower().strip()
    scored: list[tuple[int, dict[str, Any]]] = []

    for mo_name, mo_info in mos.items():
        mo_score = _score_text(mo_name, words) * 4
        mo_score += _score_text(mo_info.get("leaf") or "", words) * 3
        if query_lower in mo_name.lower():
            mo_score += 15
        leaf = mo_name.split("/")[-1]
        if query_lower == leaf.lower():
            mo_score += 20
        if mo_score <= 0:
            continue

        params = mo_info.get("parameters") or []
        scored.append((mo_score, {
            "vendor": "nokia",
            "type": "mo",
            "mo": mo_name,
            "technology": mo_info.get("technology"),
            "category": mo_info.get("category"),
            "description": mo_info.get("leaf") or mo_name,
            "parameters": [
                {
                    "name": p.get("Abbreviated Name"),
                    "full_name": p.get("Full Name"),
                    "description": _truncate(p.get("Description") or "", 320),
                }
                for p in params[:8]
            ],
            "parameter_count": len(params),
        }))

    param_to_mos = data.get("param_to_mos") or {}
    param_descriptions = data.get("param_descriptions") or {}

    seen_params: set[str] = set()
    for param_name, desc in param_descriptions.items():
        if param_name in seen_params:
            continue
        param_score = _score_text(param_name, words) * 4 + _score_text(desc, words)
        if query_lower == param_name.lower():
            param_score += 20
        if param_score <= 0:
            continue
        seen_params.add(param_name)
        parent_mos = param_to_mos.get(param_name, [])
        scored.append((param_score, {
            "vendor": "nokia",
            "type": "parameter",
            "parameter": param_name,
            "description": _truncate(desc, 480),
            "mo_list": parent_mos[:6],
            "mo_count": len(parent_mos),
        }))

    for mo_name, mo_info in mos.items():
        for p in mo_info.get("parameters") or []:
            features = p.get("Features") or ""
            feat_score = _score_text(features, words) * 3
            if feat_score <= 0:
                continue
            scored.append((feat_score, {
                "vendor": "nokia",
                "type": "parameter",
                "parameter": p.get("Abbreviated Name"),
                "description": _truncate(p.get("Description") or "", 320),
                "features": _truncate(features, 200),
                "mo_list": [mo_name],
                "mo_count": 1,
            }))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, item in scored:
        key = f"{item.get('type')}:{item.get('mo') or item.get('parameter')}"
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results
