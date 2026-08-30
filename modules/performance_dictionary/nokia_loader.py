"""Load Nokia performance dictionary from Excel (with JSON cache)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pandas as pd

_DIR = os.path.dirname(__file__)
NOKIA_PERF_DIR = os.path.join(_DIR, "Nokia Performance")
NOKIA_CACHE_DIR = os.path.join(_DIR, "data", "nokia_performance")
NOKIA_CACHE_PATH = os.path.join(_DIR, "data", "nokia_performance.json")  # legacy monolith
NOKIA_CACHE_INDEX = os.path.join(NOKIA_CACHE_DIR, "index.json")
COUNTERS_DIR = os.path.join(NOKIA_CACHE_DIR, "counters")

# Exact sheet names and aliases (RNC uses "Counter mcRNC").
ENTITY_SHEETS: dict[str, str] = {
    "Measurement List": "measurements",
    "Counter List": "counters",
    "Counter mcRNC": "counters",
    "KPI List": "kpis",
}

ID_COLUMNS = {
    "measurements": "Measurement ID",
    "counters": "Counter ID",
    "kpis": "KPI ID",
}

HEADER_MARKERS = {
    "measurements": ("Measurement ID",),
    "counters": ("Counter ID",),
    "kpis": ("KPI ID",),
}

DISPLAY_COLUMNS = {
    "measurements": [
        "Technology",
        "Measurement ID",
        "Measurement Abbreviated Name",
        "Measurement Name",
        "Measurement Description",
        "Measurement Network Profile",
        "Measurement NW Aggregation Levels",
        "Object Level",
    ],
    "counters": [
        "Technology",
        "Counter ID",
        "NetAct Name",
        "Network Element Name",
        "Measurement Name",
        "Measurement ID",
        "Counter Description",
        "Description",
        "Counter Triggering Conditions",
        "Counter Aggregation Levels",
    ],
    "kpis": [
        "Technology",
        "KPI ID",
        "KPI Abbreviation",
        "KPI Name",
        "Description",
        "Unit",
        "Measurement",
        "Formula",
        "KPI Formula (with Counter IDs)",
        "Related Counters",
    ],
}

_cache: dict[str, Any] | None = None
_index_cache: dict[str, Any] | None = None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _normalize_counter_id(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+", text):
        return text.zfill(6)
    return text


def _tech_tokens(value: str) -> list[str]:
    return [part.strip() for part in re.split(r",\s*", value or "") if part.strip()]


def _primary_technology(value: str) -> str:
    tokens = _tech_tokens(value)
    return tokens[0] if tokens else ""


def _normalize_measurement_id(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+\.?\d*", text):
        try:
            num = float(text)
            if num.is_integer():
                return str(int(num))
        except ValueError:
            pass
    return text


def _excel_engine(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return "openpyxl"
    return "xlrd"


def _source_technology_hint(filename: str) -> str:
    name = filename.lower()
    if "asbsc" in name or re.search(r"(^|[^a-z])bsc([^a-z]|$)", name):
        return "2G-BSC"
    if "wcdma" in name or "ipa_rnc" in name or "rnc" in name:
        return "3G-RNC"
    return ""


def _store_key(technology: str, entity_id: str) -> str:
    tech = (technology or "unknown").strip() or "unknown"
    return f"{tech}|{entity_id}"


def _row_from_map(row_map: dict[str, Any]) -> dict[str, str]:
    return {str(col): _clean(row_map.get(col)) for col in row_map if not str(col).startswith("Unnamed")}


def _nokia_excel_paths() -> list[str]:
    paths: list[str] = []
    if os.path.isdir(NOKIA_PERF_DIR):
        for name in sorted(os.listdir(NOKIA_PERF_DIR)):
            if name.lower().endswith((".xlsx", ".xls")) and not name.startswith("~$"):
                paths.append(os.path.join(NOKIA_PERF_DIR, name))
    return paths


def _excel_mtime() -> float:
    latest = 0.0
    for path in _nokia_excel_paths():
        try:
            latest = max(latest, os.path.getmtime(path))
        except OSError:
            continue
    return latest


def _shard_tech_name(technology: str) -> str:
    tech = (technology or "unknown").strip() or "unknown"
    safe = re.sub(r"[^A-Za-z0-9._+-]+", "_", tech)
    return safe or "unknown"


def _counter_shard_path(technology: str) -> str:
    return os.path.join(COUNTERS_DIR, f"{_shard_tech_name(technology)}.json")


def _cache_mtime() -> float:
    latest = 0.0
    for path in (NOKIA_CACHE_INDEX, NOKIA_CACHE_PATH):
        try:
            latest = max(latest, os.path.getmtime(path))
        except OSError:
            continue
    if os.path.isdir(NOKIA_CACHE_DIR):
        for root, _, files in os.walk(NOKIA_CACHE_DIR):
            for name in files:
                if not name.endswith(".json"):
                    continue
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    continue
    return latest


def _compact_row(row: dict[str, Any]) -> dict[str, str]:
    """Drop empty fields so shard files stay small enough for git."""
    return {str(key): value for key, value in row.items() if value not in (None, "")}


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _ordered_columns(entity: str, all_columns: set[str]) -> list[str]:
    preferred = DISPLAY_COLUMNS.get(entity) or []
    ordered = [col for col in preferred if col in all_columns]
    extras = sorted(
        col for col in all_columns
        if col not in ordered and not col.startswith("_") and not col.startswith("Unnamed")
    )
    return ordered + extras


def _content_key(entity: str, row: dict[str, str]) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    id_col = ID_COLUMNS[entity]
    entity_id = row.get(id_col) or ""
    tech = row.get("Technology") or ""
    skip = {"Technology", "_source", "_entity", "_technologies", "_store_id"}
    payload = tuple(sorted((k, v) for k, v in row.items() if k not in skip and v))
    return tech, entity_id, payload


def _detect_header_row(path: str, sheet_name: str, entity: str, engine: str) -> int | None:
    markers = HEADER_MARKERS.get(entity) or ()
    try:
        preview = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=None,
            nrows=20,
            engine=engine,
        )
    except Exception:
        return None

    for idx, row in preview.iterrows():
        values = {_clean(v) for v in row.tolist()}
        if any(marker in values for marker in markers):
            return int(idx)
    return None


def _sheets_for_workbook(path: str, engine: str) -> dict[str, str]:
    try:
        xl = pd.ExcelFile(path, engine=engine)
    except Exception:
        return {}

    found: dict[str, str] = {}
    for sheet_name in xl.sheet_names:
        entity = ENTITY_SHEETS.get(sheet_name)
        if entity:
            found[sheet_name] = entity
            continue
        lower = sheet_name.strip().lower()
        if lower == "measurement list":
            found[sheet_name] = "measurements"
        elif lower.startswith("counter"):
            found[sheet_name] = "counters"
        elif lower == "kpi list":
            found[sheet_name] = "kpis"
    return found


def _parse_measurement_id_and_name(combo: str) -> tuple[str, str]:
    text = (combo or "").strip()
    if not text:
        return "", ""
    match = re.match(r"^(\d+)\s*:\s*(.+)$", text)
    if match:
        return _normalize_measurement_id(match.group(1)), match.group(2).strip()
    return "", text


def _enrich_fields(entity: str, fields: dict[str, str], tech_hint: str) -> None:
    if not fields.get("Technology") and tech_hint:
        fields["Technology"] = tech_hint

    if entity == "counters":
        combo = fields.get("Measurement ID and Name") or ""
        if combo:
            mid, mname = _parse_measurement_id_and_name(combo)
            if mid and not fields.get("Measurement ID"):
                fields["Measurement ID"] = mid
            if mname and not fields.get("Measurement Name"):
                fields["Measurement Name"] = mname
        if fields.get("Description") and not fields.get("Counter Description"):
            fields["Counter Description"] = fields["Description"]

    if entity == "kpis":
        if fields.get("KPI Formula (with Counter IDs)") and not fields.get("Formula"):
            fields["Formula"] = fields["KPI Formula (with Counter IDs)"]
        elif fields.get("KPI Logical Formula") and not fields.get("Formula"):
            fields["Formula"] = fields["KPI Logical Formula"]


def _ingest_sheet(
    path: str,
    sheet_name: str,
    entity: str,
    *,
    store: dict[str, dict[str, str]],
    columns: set[str],
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]],
    sources: set[str],
) -> int:
    engine = _excel_engine(path)
    header_row = _detect_header_row(path, sheet_name, entity, engine)
    if header_row is None:
        return 0

    try:
        df = pd.read_excel(path, sheet_name=sheet_name, header=header_row, engine=engine)
    except Exception:
        return 0

    source_name = os.path.basename(path)
    tech_hint = _source_technology_hint(source_name)
    columns.update(str(col) for col in df.columns if not str(col).startswith("Unnamed"))
    added = 0

    for row_map in df.to_dict(orient="records"):
        fields = _row_from_map(row_map)
        _enrich_fields(entity, fields, tech_hint)

        id_col = ID_COLUMNS[entity]
        raw_id = fields.get(id_col) or ""
        if entity == "counters":
            entity_id = _normalize_counter_id(raw_id)
        elif entity == "measurements":
            entity_id = _normalize_measurement_id(raw_id)
        else:
            entity_id = raw_id.strip()
        fields[id_col] = entity_id
        if not entity_id:
            continue

        content_key = _content_key(entity, fields)
        if content_key in seen:
            continue
        seen.add(content_key)

        technology = fields.get("Technology") or tech_hint or "unknown"
        fields["Technology"] = technology
        store_id = _store_key(technology, entity_id)
        fields["_source"] = source_name
        fields["_entity"] = entity
        fields["_store_id"] = store_id
        fields["_technologies"] = ",".join(_tech_tokens(technology))

        # Prefer first occurrence of a store key; later sources keep distinct tech namespaces.
        if store_id in store:
            continue
        store[store_id] = fields
        sources.add(source_name)
        added += 1

    return added


def _link_counters_to_measurements(
    measurements: dict[str, dict[str, str]],
    counters: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    name_to_ids: dict[tuple[str, str], str] = {}
    for mid, row in measurements.items():
        tech = row.get("Technology") or ""
        mname = row.get("Measurement Name") or ""
        if mname:
            name_to_ids[(tech, mname)] = mid

    by_measurement: dict[str, list[str]] = {}
    for counter_store_id, row in counters.items():
        tech = row.get("Technology") or ""
        mname = row.get("Measurement Name") or ""
        mid = name_to_ids.get((tech, mname), "")
        if not mid:
            raw_mid = row.get("Measurement ID") or ""
            if raw_mid:
                candidate = _store_key(tech, raw_mid)
                if candidate in measurements:
                    mid = candidate
        if mid:
            # Keep human Measurement ID on the counter, plus link key for grouping.
            measurement_row = measurements.get(mid) or {}
            row["Measurement ID"] = measurement_row.get("Measurement ID") or row.get("Measurement ID") or ""
            row["_measurement_store_id"] = mid
        by_measurement.setdefault(mid or "__unlinked__", []).append(counter_store_id)

    for counter_ids in by_measurement.values():
        counter_ids.sort()
    return by_measurement


def build_nokia_data_from_excel() -> dict[str, Any]:
    measurements: dict[str, dict[str, str]] = {}
    counters: dict[str, dict[str, str]] = {}
    kpis: dict[str, dict[str, str]] = {}
    columns_by_entity: dict[str, set[str]] = {
        "measurements": set(),
        "counters": set(),
        "kpis": set(),
    }
    seen_by_entity: dict[str, set[tuple[str, str, tuple[tuple[str, str], ...]]]] = {
        "measurements": set(),
        "counters": set(),
        "kpis": set(),
    }
    sources: set[str] = set()
    ingest_counts = {"measurements": 0, "counters": 0, "kpis": 0}

    stores = {
        "measurements": measurements,
        "counters": counters,
        "kpis": kpis,
    }

    for path in _nokia_excel_paths():
        engine = _excel_engine(path)
        for sheet_name, entity in _sheets_for_workbook(path, engine).items():
            added = _ingest_sheet(
                path,
                sheet_name,
                entity,
                store=stores[entity],
                columns=columns_by_entity[entity],
                seen=seen_by_entity[entity],
                sources=sources,
            )
            ingest_counts[entity] += added

    counters_by_measurement = _link_counters_to_measurements(measurements, counters)

    technologies: set[str] = set()
    for bucket in (measurements, counters, kpis):
        for row in bucket.values():
            for token in _tech_tokens(row.get("Technology") or ""):
                technologies.add(token)

    measurement_index = []
    for mid, row in sorted(
        measurements.items(),
        key=lambda item: (item[1].get("Technology") or "", item[1].get("Measurement ID") or "", item[0]),
    ):
        counter_count = len(counters_by_measurement.get(mid, []))
        measurement_index.append({
            "id": mid,
            "raw_id": row.get("Measurement ID") or "",
            "technology": _primary_technology(row.get("Technology") or ""),
            "technologies": _tech_tokens(row.get("Technology") or ""),
            "name": row.get("Measurement Name") or "",
            "abbr": row.get("Measurement Abbreviated Name") or "",
            "description": row.get("Measurement Description") or "",
            "source": row.get("_source") or "",
            "counter_count": counter_count,
        })

    kpi_index = []
    for kid, row in sorted(
        kpis.items(),
        key=lambda item: (item[1].get("Technology") or "", item[1].get("KPI ID") or "", item[0]),
    ):
        kpi_index.append({
            "id": kid,
            "raw_id": row.get("KPI ID") or "",
            "technology": _primary_technology(row.get("Technology") or ""),
            "technologies": _tech_tokens(row.get("Technology") or ""),
            "name": row.get("KPI Name") or "",
            "abbr": row.get("KPI Abbreviation") or "",
            "description": row.get("Description") or "",
            "source": row.get("_source") or "",
        })

    columns = {
        entity: _ordered_columns(entity, columns_by_entity[entity])
        for entity in ("measurements", "counters", "kpis")
    }

    return {
        "columns": columns,
        "measurements": measurements,
        "counters": counters,
        "kpis": kpis,
        "measurement_index": measurement_index,
        "kpi_index": kpi_index,
        "counters_by_measurement": counters_by_measurement,
        "meta": {
            "source": sorted(sources),
            "measurement_count": len(measurements),
            "counter_count": len(counters),
            "kpi_count": len(kpis),
            "technologies": sorted(technologies),
            "ingest_counts": ingest_counts,
        },
    }


def write_nokia_cache(data: dict[str, Any] | None = None) -> str:
    """Write sharded JSON cache (index + entity files + per-technology counters)."""
    payload = data if data is not None else build_nokia_data_from_excel()
    os.makedirs(COUNTERS_DIR, exist_ok=True)

    counters = payload.get("counters") or {}
    counters_by_tech: dict[str, dict[str, dict[str, str]]] = {}
    for counter_id, row in counters.items():
        tech = (row.get("Technology") or "").strip()
        if not tech and "|" in counter_id:
            tech = counter_id.split("|", 1)[0]
        tech = tech or "unknown"
        counters_by_tech.setdefault(tech, {})[counter_id] = _compact_row(row)

    shard_map: dict[str, str] = {}
    for tech, rows in sorted(counters_by_tech.items()):
        shard_name = f"{_shard_tech_name(tech)}.json"
        shard_map[tech] = shard_name
        _write_json(os.path.join(COUNTERS_DIR, shard_name), rows)

    measurements = {
        key: _compact_row(row)
        for key, row in (payload.get("measurements") or {}).items()
    }
    kpis = {
        key: _compact_row(row)
        for key, row in (payload.get("kpis") or {}).items()
    }
    _write_json(os.path.join(NOKIA_CACHE_DIR, "measurements.json"), measurements)
    _write_json(os.path.join(NOKIA_CACHE_DIR, "kpis.json"), kpis)

    index_payload = {
        "format": "sharded_v1",
        "columns": payload.get("columns") or {},
        "measurement_index": payload.get("measurement_index") or [],
        "kpi_index": payload.get("kpi_index") or [],
        "counters_by_measurement": payload.get("counters_by_measurement") or {},
        "meta": {
            **(payload.get("meta") or {}),
            "cache_format": "sharded_v1",
            "counter_shards": shard_map,
        },
        "files": {
            "measurements": "measurements.json",
            "kpis": "kpis.json",
            "counters_dir": "counters",
        },
    }
    _write_json(NOKIA_CACHE_INDEX, index_payload)

    # Remove legacy monolith if present so it is not re-uploaded by accident.
    try:
        if os.path.isfile(NOKIA_CACHE_PATH):
            os.remove(NOKIA_CACHE_PATH)
    except OSError:
        pass

    return NOKIA_CACHE_INDEX


def _load_sharded_cache() -> dict[str, Any]:
    index = _read_json(NOKIA_CACHE_INDEX)
    files = index.get("files") or {}
    measurements_name = files.get("measurements") or "measurements.json"
    kpis_name = files.get("kpis") or "kpis.json"
    counters_dirname = files.get("counters_dir") or "counters"

    measurements = _read_json(os.path.join(NOKIA_CACHE_DIR, measurements_name))
    kpis = _read_json(os.path.join(NOKIA_CACHE_DIR, kpis_name))

    counters: dict[str, dict[str, str]] = {}
    counters_dir = os.path.join(NOKIA_CACHE_DIR, counters_dirname)
    if os.path.isdir(counters_dir):
        for name in sorted(os.listdir(counters_dir)):
            if not name.endswith(".json"):
                continue
            shard = _read_json(os.path.join(counters_dir, name))
            if isinstance(shard, dict):
                counters.update(shard)

    return {
        "columns": index.get("columns") or {},
        "measurements": measurements if isinstance(measurements, dict) else {},
        "counters": counters,
        "kpis": kpis if isinstance(kpis, dict) else {},
        "measurement_index": index.get("measurement_index") or [],
        "kpi_index": index.get("kpi_index") or [],
        "counters_by_measurement": index.get("counters_by_measurement") or {},
        "meta": index.get("meta") or {},
    }


def load_nokia_data(force_refresh: bool = False) -> dict[str, Any]:
    global _cache
    excel_mtime = _excel_mtime()
    cache_mtime = _cache_mtime()
    cache_stale = cache_mtime < excel_mtime if excel_mtime else False

    if not force_refresh and _cache is not None and not cache_stale:
        return _cache

    if not force_refresh and os.path.isfile(NOKIA_CACHE_INDEX) and not cache_stale:
        _cache = _load_sharded_cache()
        return _cache

    # Legacy single-file cache support (migrate on load).
    if not force_refresh and os.path.isfile(NOKIA_CACHE_PATH) and not cache_stale:
        legacy = _read_json(NOKIA_CACHE_PATH)
        write_nokia_cache(legacy)
        _cache = legacy
        return _cache

    _cache = build_nokia_data_from_excel()
    if _cache.get("measurement_index"):
        write_nokia_cache(_cache)
    return _cache


def get_index_payload() -> dict[str, Any]:
    global _index_cache
    excel_mtime = _excel_mtime()
    try:
        index_mtime = os.path.getmtime(NOKIA_CACHE_INDEX)
    except OSError:
        index_mtime = 0.0
    stale = bool(excel_mtime) and index_mtime < excel_mtime

    if _index_cache is not None and not stale:
        return _index_cache

    if os.path.isfile(NOKIA_CACHE_INDEX) and not stale:
        index = _read_json(NOKIA_CACHE_INDEX)
        payload = {
            "columns": index.get("columns") or {},
            "measurement_index": index.get("measurement_index") or [],
            "kpi_index": index.get("kpi_index") or [],
            "meta": index.get("meta") or {},
        }
        _index_cache = payload
        return payload

    data = load_nokia_data()
    payload = {
        "columns": data.get("columns") or {},
        "measurement_index": data.get("measurement_index") or [],
        "kpi_index": data.get("kpi_index") or [],
        "meta": data.get("meta") or {},
    }
    _index_cache = payload
    return payload


def _lookup_row(store: dict[str, dict[str, str]], key: str, id_col: str) -> tuple[str, dict[str, str] | None]:
    if key in store:
        return key, store[key]
    for store_id, row in store.items():
        if store_id.endswith(f"|{key}") or row.get(id_col) == key:
            return store_id, row
    return key, None


def get_measurement(measurement_id: str) -> dict[str, Any]:
    data = load_nokia_data()
    store_id, row = _lookup_row(data.get("measurements") or {}, measurement_id, "Measurement ID")
    if not row:
        return {"id": measurement_id, "row": None, "counter_ids": []}
    counter_ids = (data.get("counters_by_measurement") or {}).get(store_id) or []
    return {
        "id": store_id,
        "row": row,
        "counter_ids": counter_ids,
        "counter_count": len(counter_ids),
    }


def get_counters_for_measurement(measurement_id: str) -> dict[str, Any]:
    data = load_nokia_data()
    store_id, _ = _lookup_row(data.get("measurements") or {}, measurement_id, "Measurement ID")
    counter_ids = (data.get("counters_by_measurement") or {}).get(store_id) or []
    counters = data.get("counters") or {}
    rows = [counters[cid] for cid in counter_ids if cid in counters]
    return {
        "measurement_id": store_id,
        "rows": rows,
        "total": len(rows),
    }


def get_counter(counter_id: str) -> dict[str, Any]:
    data = load_nokia_data()
    normalized = _normalize_counter_id(counter_id)
    store_id, row = _lookup_row(data.get("counters") or {}, normalized, "Counter ID")
    return {"id": store_id, "row": row}


def get_kpi(kpi_id: str) -> dict[str, Any]:
    data = load_nokia_data()
    key = kpi_id.strip()
    store_id, row = _lookup_row(data.get("kpis") or {}, key, "KPI ID")
    return {"id": store_id, "row": row}


def search_nokia_performance(
    query: str,
    *,
    entity: str = "all",
    limit: int = 500,
) -> dict[str, Any]:
    data = load_nokia_data()
    columns = data.get("columns") or {}
    term = (query or "").strip().lower()
    if len(term) < 2:
        return {"results": [], "total": 0, "capped": False}

    words = term.split()
    entity = (entity or "all").lower()
    buckets: list[tuple[str, dict[str, dict[str, str]]]] = []
    if entity in ("all", "measurements"):
        buckets.append(("measurements", data.get("measurements") or {}))
    if entity in ("all", "counters"):
        buckets.append(("counters", data.get("counters") or {}))
    if entity in ("all", "kpis"):
        buckets.append(("kpis", data.get("kpis") or {}))

    results: list[dict[str, Any]] = []
    capped = False

    for bucket_name, store in buckets:
        cols = columns.get(bucket_name) or (list(next(iter(store.values())).keys()) if store else [])
        for entity_id, row in store.items():
            blob = " ".join(str(row.get(col) or "") for col in cols).lower()
            if all(w in blob for w in words):
                results.append({
                    "entity": bucket_name,
                    "id": entity_id,
                    "technology": row.get("Technology") or "",
                    "title": _result_title(bucket_name, row),
                    "subtitle": _result_subtitle(bucket_name, row),
                    "row": row,
                })
                if len(results) >= limit:
                    capped = True
                    break
        if capped:
            break

    return {"results": results, "total": len(results), "capped": capped}


def _result_title(entity: str, row: dict[str, str]) -> str:
    if entity == "measurements":
        return row.get("Measurement Abbreviated Name") or row.get("Measurement Name") or row.get("Measurement ID") or ""
    if entity == "counters":
        return row.get("NetAct Name") or row.get("Network Element Name") or row.get("Counter ID") or ""
    return row.get("KPI Abbreviation") or row.get("KPI Name") or row.get("KPI ID") or ""


def _result_subtitle(entity: str, row: dict[str, str]) -> str:
    if entity == "measurements":
        return row.get("Measurement Name") or ""
    if entity == "counters":
        return row.get("Measurement Name") or ""
    return row.get("KPI Name") or row.get("Description") or ""
