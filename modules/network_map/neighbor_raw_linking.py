"""
Resolve slim raw neighbor export rows (``nokia_neighbor_*`` / ``huawei_neighbor_*``) to map line segments.

The ``vendor`` argument on linking APIs is the **source** equipment vendor: metadata lookups for the
neighbor **source** cell honor it; **target** cells resolve against all vendors (interop / different vendor on the far end).

Linking rules (sanitized CSV headers, see scripts/load_nokia_neighbor_raw_to_db.py):
- 2G: source = Segment Name, target = CI — both match ``cells_2g.cell_id`` (with string/int key variants).
  Attempts: prefer ``HO to the Adjacent cell: Att (c15001)`` (sanitized) / ``c15001`` in column name; successes ignored for 2G.
- 3G: source = ``scid_id``, target = ``tcid_id`` (or CI) — both match ``cells_3g.cell_id`` (with string/int key variants); nodeB+cell_id
  fallback remains. Attempts / completions: slim columns ``ho_attempts`` / ``ho_completions``, or M1013C0 / M1013C1 in headers.
- 4G intra: table ``nokia_neighbor_4g_intra`` — intra-eNB neighbor attempts, Adj Intra eNB HO SR as ``ho_success_rate``.
- 4G inter: table ``nokia_neighbor_4g_inter`` — inter-eNB attempts per neighbor relationship, Adj Inter eNB HO SR.
  Linking uses **LTE FDD** metadata only (``cells_4g_fdd``): TDD is omitted from neighbor HO resolution.
  Geometry: source LNCEL name → ``cell_name``; target ``eci_id`` → eNB/cell keys.
"""

from __future__ import annotations

import math
import re
import sqlite3
from typing import Any, Callable

from sync_config import METADATA_DB


def _norm_header_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _norm_cell_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _to_int(v: object) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s.replace(",", "")))
    except (TypeError, ValueError):
        return None


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace("\u00a0", " ")
    if not s:
        return None
    s = s.replace(",", "").replace(" ", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(v).strip().replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except (TypeError, ValueError):
        return None


def neighbor_ho_failures(
    attempts: object,
    rate_percent: float | None,
    successes: float | None,
) -> float | None:
    """Failed HOs ≈ attempts × (1 − SR) with SR as percent (0–100); else ``attempts − successes`` when known."""
    att = _to_float(attempts)
    if att is None or att <= 0:
        return None
    if rate_percent is not None and math.isfinite(float(rate_percent)):
        rp = max(0.0, min(100.0, float(rate_percent)))
        return att * (1.0 - rp / 100.0)
    if successes is not None:
        su = _to_float(successes)
        if su is not None:
            return max(0.0, att - su)
    return None


def _eci_split(eci_val: object) -> tuple[int | None, int | None]:
    """E-UTRAN Cell Identity: ``eNodeB_id = ECI // 256``, ``cell_id = ECI % 256`` (matches metadata keys)."""
    eci = _to_int(eci_val)
    if eci is None or eci < 0:
        return None, None
    enb = eci // 256
    cid = eci % 256
    return enb, cid


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [str(r[1]) for r in rows]


def _pick_ci_column(cols: list[str]) -> str | None:
    """Prefer an exact 'CI' column over names that merely contain 'ci' (e.g. PCI)."""
    for c in cols:
        if _norm_header_key(c) == "ci":
            return c
    return _pick_column(cols, "Target_CI", "target_ci", "TargetCI", "tgt_ci")


def _pick_column(cols: list[str], *candidates: str) -> str | None:
    """Match first candidate by normalized header (handles Segment_Name vs segmentname)."""
    by_norm = {_norm_header_key(c): c for c in cols}
    for cand in candidates:
        k = _norm_header_key(cand)
        if k in by_norm:
            return by_norm[k]
    for cand in candidates:
        k = _norm_header_key(cand)
        if len(k) < 4:
            continue
        for nk, actual in by_norm.items():
            if nk.endswith(k) or (len(k) >= 6 and k in nk):
                return actual
    return None


def _pick_3g_neighbor_attempt_column(cols: list[str]) -> str | None:
    """NetAct UMTS intra-freq SHO adjacent: M1013C0 = SHO_ADJ_INTRA_FREQ_SHO_ATT (sanitized names vary)."""
    for c in cols:
        nk = _norm_header_key(c)
        if "m1013c0" in nk:
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "intrafreq" in nk and "sho" in nk and "att" in nk and "compl" not in nk:
            return c
    return None


def _pick_4g_neighbor_attempt_column(cols: list[str]) -> str | None:
    """e.g. 'Intra eNB HO attempts per neighbor cell'. Excludes inter-eNB counters."""
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk:
            continue
        if "intra" in nk and "enb" in nk and "neighbor" in nk and "attempt" in nk:
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk:
            continue
        if "intra" in nk and "enb" in nk and ("attempt" in nk or "att" in nk) and "nbr" in nk:
            return c
    return None


def _pick_4g_neighbor_sr_column(cols: list[str]) -> str | None:
    """e.g. 'Adj Intra eNB HO SR' — success rate, not raw success counts."""
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk:
            continue
        if "adj" in nk and "intra" in nk and "enb" in nk and ("sr" in nk or "successrate" in nk):
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk:
            continue
        if "intra" in nk and "enb" in nk and ("sr" in nk or "successrate" in nk) and "ho" in nk:
            return c
    return None


def _pick_4g_inter_attempt_column(cols: list[str]) -> str | None:
    """e.g. 'Number of Inter eNB Handover attempts per neighbor cell relationship'."""
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk and "neighbor" in nk and "attempt" in nk:
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk and ("attempt" in nk or "att" in nk) and "nbr" in nk:
            return c
    return None


def _pick_4g_inter_sr_column(cols: list[str]) -> str | None:
    """e.g. 'Adj Inter eNB HO SR'."""
    for c in cols:
        nk = _norm_header_key(c)
        if "adj" in nk and "inter" in nk and "enb" in nk and ("sr" in nk or "successrate" in nk):
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "inter" in nk and "enb" in nk and ("sr" in nk or "successrate" in nk) and "ho" in nk:
            return c
    return None


def _normalize_ho_success_rate_percent(val: object) -> float | None:
    """NetAct may export SR as 0–1 ratio or 0–100 percent."""
    v = _to_float(val)
    if v is None or not math.isfinite(v):
        return None
    if v < 0:
        return 0.0
    if v <= 1.00001:
        return v * 100.0
    return min(v, 100.0)


def _pick_3g_neighbor_completion_column(cols: list[str]) -> str | None:
    """M1013C1 = SHO_ADJ_INTRA_FREQ_SHO_COMPL."""
    for c in cols:
        nk = _norm_header_key(c)
        if "m1013c1" in nk:
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "intrafreq" in nk and "sho" in nk and ("compl" in nk or "complete" in nk):
            return c
    return None


def _pick_2g_neighbor_attempt_column(cols: list[str]) -> str | None:
    """
    NetAct GSM neighbor export: 'HO to the Adjacent cell: Att (c15001)' → sanitized unique name.
    Prefer explicit counter id c15001, else HO + Adjacent + Att.
    """
    for c in cols:
        nk = _norm_header_key(c)
        if "c15001" in nk:
            return c
    for c in cols:
        nk = _norm_header_key(c)
        if "adjacent" in nk and "att" in nk and ("ho" in nk or "handover" in nk or "hho" in nk):
            return c
    return None


def _export_cell_id_keys(val: object) -> frozenset[str]:
    """Keys to match neighbor export Segment / CI values to metadata cell_id (text or int)."""
    s = str(val or "").strip()
    if not s:
        return frozenset()
    out: set[str] = {s}
    lo = s.lower()
    out.add(lo)
    n = _to_int(val)
    if n is not None:
        out.add(str(n))
    return frozenset(out)


def _pick_ho_metric_column(cols: list[str]) -> tuple[str | None, str | None]:
    """Return (attempts_col, successes_col) if found."""
    by_norm = {_norm_header_key(c): c for c in cols}
    att = succ = None
    for nk, actual in by_norm.items():
        if att is None and "attempt" in nk and ("ho" in nk or "handover" in nk or "nbr" in nk or "hho" in nk):
            att = actual
        if att is None and nk in ("hoattempts", "handoverattempts", "nbrofattempts", "attempts"):
            att = actual
        if succ is None and "success" in nk and ("ho" in nk or "handover" in nk or "hho" in nk):
            succ = actual
        if succ is None and nk in ("hosuccesses", "handoversuccesses", "successes"):
            succ = actual
    if att is None:
        for nk, actual in by_norm.items():
            if "ho" in nk and "att" in nk:
                att = actual
                break
    return att, succ


def _meta_row_to_coord(
    cell_name: object,
    site_id: object,
    lat: object,
    lng: object,
    region: object | None = None,
    azimuth: object | None = None,
    vendor: object | None = None,
) -> dict[str, Any] | None:
    la = _to_float(lat)
    lo = _to_float(lng)
    if la is None or lo is None or not math.isfinite(la) or not math.isfinite(lo):
        return None
    sid = str(site_id).strip() if site_id is not None else ""
    try:
        cluster = int(float(sid)) // 100 if sid.replace(".", "", 1).isdigit() else None
    except (TypeError, ValueError):
        cluster = None
    out: dict[str, Any] = {
        "cell_name": str(cell_name or "").strip(),
        "site_id": site_id,
        "lat": la,
        "lng": lo,
        "region": region,
        "cluster": cluster,
    }
    az = _to_float(azimuth)
    if az is not None and math.isfinite(az):
        out["azimuth"] = az
    v = str(vendor or "").strip()
    if v:
        out["vendor"] = v
    return out


def _coord_vendor_matches(coord: dict | None, vendor: str) -> bool:
    """If ``vendor`` is set and not ``all``, require metadata ``coord['vendor']`` to match (source-side filter)."""
    v = (vendor or "").strip()
    if not v or v.lower() == "all":
        return True
    cv = str((coord or {}).get("vendor") or "").strip().lower()
    return cv == v.lower()


def _vendor_sql_clause(vendor: str) -> tuple[str, list[str]]:
    v = (vendor or "").strip()
    if not v or v.lower() == "all":
        return "", []
    return "AND LOWER(TRIM(COALESCE(vendor, ''))) = LOWER(TRIM(?))", [v]


def _load_2g_indexes(
    meta: sqlite3.Connection,
) -> tuple[dict[str, dict], dict[tuple[str, str], dict], dict[str, dict]]:
    """by_cell_name_norm, by (site_id, cell_id str), by any key in _export_cell_id_keys(metadata cell_id).

    Loads **all** vendors; apply ``_coord_vendor_matches`` when resolving the **source** side only.
    """
    by_name: dict[str, dict] = {}
    by_site_cell: dict[tuple[str, str], dict] = {}
    by_cell_id: dict[str, dict] = {}
    q = """
        SELECT cell_name, site_id, cell_id, lat, long, area, azimuth, vendor
        FROM cells_2g
        WHERE lat IS NOT NULL AND long IS NOT NULL
    """
    for r in meta.execute(q).fetchall():
        coord = _meta_row_to_coord(r[0], r[1], r[3], r[4], r[5], r[6], vendor=r[7])
        if not coord:
            continue
        cn = _norm_cell_key(r[0])
        if cn and cn not in by_name:
            by_name[cn] = coord
        site = str(r[1] or "").strip()
        cid = str(r[2] or "").strip()
        if site and cid:
            by_site_cell[(site, cid)] = coord
        for k in _export_cell_id_keys(r[2]):
            if k and k not in by_cell_id:
                by_cell_id[k] = coord
    return by_name, by_site_cell, by_cell_id


def _lookup_2g_by_cell_id(val: object, by_cell_id: dict[str, dict]) -> dict | None:
    for k in _export_cell_id_keys(val):
        hit = by_cell_id.get(k)
        if hit:
            return hit
    return None


def _lookup_2g_by_cell_id_for_vendor(
    val: object, by_cell_id: dict[str, dict], vendor: str
) -> dict | None:
    """Like ``_lookup_2g_by_cell_id`` but only returns a coord whose metadata vendor passes ``vendor``."""
    for k in _export_cell_id_keys(val):
        hit = by_cell_id.get(k)
        if hit and _coord_vendor_matches(hit, vendor):
            return hit
    return None


def _lookup_3g_by_cell_id(val: object, by_cell_id: dict[str, dict]) -> dict | None:
    for k in _export_cell_id_keys(val):
        hit = by_cell_id.get(k)
        if hit:
            return hit
    return None


def _lookup_3g_by_cell_id_for_vendor(
    val: object, by_cell_id: dict[str, dict], vendor: str
) -> dict | None:
    for k in _export_cell_id_keys(val):
        hit = by_cell_id.get(k)
        if hit and _coord_vendor_matches(hit, vendor):
            return hit
    return None


def _load_3g_indexes(
    meta: sqlite3.Connection,
) -> tuple[dict[str, dict], dict[tuple[str, str], dict], dict[str, dict]]:
    """by_cell_name_norm, by (nodeb_id, cell_id), by export keys for metadata ``cell_id`` (UMTS CI)."""
    by_name: dict[str, dict] = {}
    by_node_cell: dict[tuple[str, str], dict] = {}
    by_cell_id: dict[str, dict] = {}
    q = """
        SELECT cell_name, nodeb_id, cell_id, lat, long, area, azimuth, vendor
        FROM cells_3g
        WHERE lat IS NOT NULL AND long IS NOT NULL
    """
    for r in meta.execute(q).fetchall():
        coord = _meta_row_to_coord(r[0], r[1], r[3], r[4], r[5], r[6], vendor=r[7])
        if not coord:
            continue
        cn = _norm_cell_key(r[0])
        if cn and cn not in by_name:
            by_name[cn] = coord
        nb = str(r[1] or "").strip()
        cid = str(r[2] or "").strip()
        if nb and cid:
            by_node_cell[(nb, cid)] = coord
        for k in _export_cell_id_keys(r[2]):
            if k and k not in by_cell_id:
                by_cell_id[k] = coord
    return by_name, by_node_cell, by_cell_id


def _load_4g_indexes(
    meta: sqlite3.Connection,
    table: str,
) -> tuple[dict[str, dict], dict[tuple[int, int], dict]]:
    by_name: dict[str, dict] = {}
    by_enb_cell: dict[tuple[int, int], dict] = {}
    q = f"""
        SELECT cell_name, enb_id_actual, cell_id, lat, long, area, azimuth, vendor
        FROM "{table}"
        WHERE lat IS NOT NULL AND long IS NOT NULL
    """
    for r in meta.execute(q).fetchall():
        coord = _meta_row_to_coord(r[0], r[1], r[3], r[4], r[5], r[6], vendor=r[7])
        if not coord:
            continue
        cn = _norm_cell_key(r[0])
        if cn and cn not in by_name:
            by_name[cn] = coord
        enb = _to_int(r[1])
        cid = _to_int(r[2])
        if enb is not None and cid is not None:
            by_enb_cell[(enb, cid)] = coord
    return by_name, by_enb_cell


def _resolve_2g_target(
    ci_raw: object,
    by_name: dict[str, dict],
    by_site_cell: dict[tuple[str, str], dict],
    src_site: object | None,
) -> dict | None:
    ci_s = str(ci_raw or "").strip()
    if not ci_s:
        return None
    k = _norm_cell_key(ci_raw)
    if k in by_name:
        return by_name[k]
    site = str(src_site or "").strip()
    if site:
        hit = by_site_cell.get((site, ci_s))
        if hit:
            return hit
        hit = by_site_cell.get((site, str(_to_int(ci_raw) or ci_s)))
        if hit:
            return hit
    for (s, c), coord in by_site_cell.items():
        if c == ci_s or c == str(_to_int(ci_raw) or ""):
            if not site or s == site:
                return coord
    return by_name.get(_norm_cell_key(ci_s))


def _resolve_3g_target(
    tcid_raw: object,
    by_name: dict[str, dict],
    by_node_cell: dict[tuple[str, str], dict],
    src_node: object | None,
    by_cell_id: dict[str, dict],
) -> dict | None:
    hit = _lookup_3g_by_cell_id(tcid_raw, by_cell_id)
    if hit:
        return hit
    ci_s = str(tcid_raw or "").strip()
    if not ci_s:
        return None
    k = _norm_cell_key(tcid_raw)
    if k in by_name:
        return by_name[k]
    nb = str(src_node or "").strip()
    if nb:
        hit = by_node_cell.get((nb, ci_s))
        if hit:
            return hit
        ci_int = _to_int(tcid_raw)
        if ci_int is not None:
            hit = by_node_cell.get((nb, str(ci_int)))
            if hit:
                return hit
    if not nb:
        for (n, c), coord in by_node_cell.items():
            if c == ci_s or c == str(_to_int(tcid_raw) or ""):
                return coord
    return None


def _resolve_3g_source(
    scid_raw: object,
    by_name: dict[str, dict],
    by_node_cell: dict[tuple[str, str], dict],
    by_cell_id: dict[str, dict],
    source_vendor: str = "",
) -> dict | None:
    if scid_raw is None or str(scid_raw).strip() == "":
        return None
    hit = _lookup_3g_by_cell_id_for_vendor(scid_raw, by_cell_id, source_vendor)
    if hit:
        return hit
    k = _norm_cell_key(scid_raw)
    if k in by_name:
        cand = by_name[k]
        if _coord_vendor_matches(cand, source_vendor):
            return cand
    sid = str(scid_raw).strip()
    int_sid = _to_int(scid_raw)
    for (nb, cid), coord in by_node_cell.items():
        if cid == sid or (int_sid is not None and cid == str(int_sid)):
            if _coord_vendor_matches(coord, source_vendor):
                return coord
    return None


def _resolve_4g_target(
    eci_raw: object,
    by_enb_cell: dict[tuple[int, int], dict],
) -> dict | None:
    enb, cid = _eci_split(eci_raw)
    if enb is None or cid is None:
        return None
    return by_enb_cell.get((enb, cid))


_SLIM_4G_RAW_TABLES = frozenset(
    {
        "nokia_neighbor_4g",
        "nokia_neighbor_4g_intra",
        "nokia_neighbor_4g_inter",
        "huawei_neighbor_4g",
        "huawei_neighbor_4g_intra",
        "huawei_neighbor_4g_inter",
    }
)


def _is_slim_neighbor_table(raw_table: str, cols: list[str]) -> bool:
    if raw_table.endswith("_neighbor_2g"):
        return "source_cell_id" in cols and "target_cell_id" in cols
    if raw_table.endswith("_neighbor_3g"):
        return "scid_id" in cols and "tcid_id" in cols
    if raw_table in _SLIM_4G_RAW_TABLES:
        return "source_lncel_name" in cols and "eci_id" in cols
    return False


def _pick_col_norm_substrings(cols: list[str], *needles: str) -> str | None:
    """First column whose normalized header contains every needle substring."""
    for c in cols:
        nk = _norm_header_key(c)
        if all(n in nk for n in needles):
            return c
    return None


def _gather_2g_export_keys_for_scope(
    meta: sqlite3.Connection,
    vendor: str,
    site_id_filter: str,
    cell_norm: str,
) -> list[str]:
    """Keys that may appear in 2G neighbor source/target columns for the selected site or cell."""
    clause, vp = _vendor_sql_clause(vendor)
    site = (site_id_filter or "").strip()
    cell_n = (cell_norm or "").strip()
    q = f"""
        SELECT cell_name, cell_id, site_id
        FROM cells_2g
        WHERE lat IS NOT NULL AND long IS NOT NULL
          {clause}
    """
    rows = meta.execute(q, vp).fetchall()
    picked: list[tuple[object, object]] = []
    for cn, cid, sid in rows:
        if site and str(sid or "").strip() != site:
            continue
        if cell_n and _norm_cell_key(cn) != cell_n:
            continue
        picked.append((cn, cid))
    if not picked:
        return []
    keys: set[str] = set()
    for cn, cid in picked:
        keys.update(_export_cell_id_keys(cid))
        keys.update(_export_cell_id_keys(cn))
        nk = _norm_cell_key(cn)
        if nk:
            keys.add(nk)
    return [k for k in keys if k]


def _gather_3g_export_keys_for_scope(
    meta: sqlite3.Connection,
    vendor: str,
    site_id_filter: str,
    cell_norm: str,
) -> list[str]:
    clause, vp = _vendor_sql_clause(vendor)
    site = (site_id_filter or "").strip()
    cell_n = (cell_norm or "").strip()
    q = f"""
        SELECT cell_name, cell_id, nodeb_id
        FROM cells_3g
        WHERE lat IS NOT NULL AND long IS NOT NULL
          {clause}
    """
    rows = meta.execute(q, vp).fetchall()
    keys: set[str] = set()
    for cn, cid, sid in rows:
        if site and str(sid or "").strip() != site and str(_to_int(sid) or "") != site:
            continue
        if cell_n and _norm_cell_key(cn) != cell_n:
            continue
        keys.update(_export_cell_id_keys(cid))
        keys.update(_export_cell_id_keys(cn))
    return [k for k in keys if k]


def _gather_4g_lncel_and_eci_for_scope(
    meta: sqlite3.Connection,
    vendor: str,
    tech_u: str,
    site_id_filter: str,
    cell_norm: str,
) -> tuple[list[str], list[int]]:
    """LNCEL names (normalized lower) and ECIs for cells on the eNB (site) or matching cell_norm.

    Neighbor HO exports are aligned to LTE FDD only (no TDD in this pipeline).
    """
    clause, vp = _vendor_sql_clause(vendor)
    site = (site_id_filter or "").strip()
    cell_n = (cell_norm or "").strip()
    names: set[str] = set()
    ecis: set[int] = set()
    for table in ("cells_4g_fdd",):
        q = f"""
            SELECT cell_name, enb_id_actual, cell_id
            FROM "{table}"
            WHERE lat IS NOT NULL AND long IS NOT NULL
              {clause}
        """
        for cn, enb, cid in meta.execute(q, vp).fetchall():
            if site:
                eb = str(enb or "").strip()
                if eb != site and str(_to_int(enb) or "") != site:
                    continue
            if cell_n and _norm_cell_key(cn) != cell_n:
                continue
            nk = _norm_cell_key(cn)
            if nk:
                names.add(nk)
            enb_i = _to_int(enb)
            cid_i = _to_int(cid)
            if enb_i is not None and cid_i is not None:
                ecis.add(enb_i * 256 + cid_i)
    return sorted(names), sorted(ecis)


def _sql_scope_in_two_text_columns(
    col_a: str,
    col_b: str,
    values: list[str],
) -> tuple[str, list[str]] | None:
    """(TRIM(col_a)) IN (...) OR (TRIM(col_b)) IN (...)."""
    vals = [str(v) for v in values if str(v).strip()][:3500]
    if not vals:
        return None
    ph = ",".join("?" * len(vals))
    sql = (
        f'(TRIM(CAST("{col_a}" AS TEXT)) IN ({ph})) OR '
        f'(TRIM(CAST("{col_b}" AS TEXT)) IN ({ph}))'
    )
    return sql, vals + vals


def _sql_scope_4g_slim(
    src_col: str,
    eci_col: str,
    lncel_norms: list[str],
    ecis: list[int],
) -> tuple[str, list[Any]] | None:
    parts: list[str] = []
    params: list[Any] = []
    if lncel_norms:
        ph = ",".join("?" * len(lncel_norms))
        parts.append(f'LOWER(TRIM(CAST("{src_col}" AS TEXT))) IN ({ph})')
        params.extend(lncel_norms)
    if ecis:
        ph = ",".join("?" * len(ecis))
        parts.append(f'CAST(TRIM(CAST("{eci_col}" AS TEXT)) AS INTEGER) IN ({ph})')
        params.extend(ecis)
    if not parts:
        return None
    return "(" + " OR ".join(parts) + ")", params


def _sql_scope_huawei_wide_4g(
    src_col: str,
    enb_col: str,
    cid_col: str,
    lncel_norms: list[str],
    ecis: list[int],
) -> tuple[str, list[Any]] | None:
    """Narrow Huawei wide 4G PRS: source name in scope OR target ECI (eNB*256 + cell_id) in scope."""
    parts: list[str] = []
    params: list[Any] = []
    if lncel_norms:
        ph = ",".join("?" * len(lncel_norms))
        parts.append(f'LOWER(TRIM(CAST("{src_col}" AS TEXT))) IN ({ph})')
        params.extend(lncel_norms)
    if ecis:
        ph = ",".join("?" * len(ecis))
        eci_expr = (
            f'(CAST(TRIM(CAST("{enb_col}" AS TEXT)) AS INTEGER) * 256 + '
            f'(ABS(CAST(TRIM(CAST("{cid_col}" AS TEXT)) AS INTEGER)) % 256))'
        )
        parts.append(f"({eci_expr} IN ({ph}))")
        params.extend(ecis)
    if not parts:
        return None
    return "(" + " OR ".join(parts) + ")", params


def build_raw_neighbor_lines(
    *,
    neighbor_conn: sqlite3.Connection,
    raw_table: str,
    technology: str,
    vendor: str,
    cell_norm: str,
    site_id_filter: str,
    min_attempts: float,
    max_lines: int,
    max_scan_rows: int = 8000,
    failures_only: bool = False,
    min_failures: float = 1.0,
) -> tuple[list[dict], int, int, str | None, str | None]:
    """
    Returns (lines, skipped_missing_coords, total_candidates, period_start, message).

    ``vendor`` restricts metadata matches for the **source** cell only (``all`` = any vendor).
    Target coordinates are resolved from the full metadata inventory so the far end can be another vendor.

    When ``cell_norm`` is set (user picked a cell), only handovers **from** that cell are kept
    (resolved source ``cell_name`` matches); rows where that cell is only the target are dropped.

    When ``failures_only`` is true, only links with estimated failures **≥ min_failures**
    (default ``1.0`` so near-zero noise is excluded). The attempts floor ``min_attempts`` is **not**
    applied in that mode (only ``attempts > 0``). Rows without SR/completions are omitted.
    """
    allowed = {
        "nokia_neighbor_2g",
        "nokia_neighbor_3g",
        "nokia_neighbor_4g",
        "nokia_neighbor_4g_intra",
        "nokia_neighbor_4g_inter",
        "huawei_neighbor_2g",
        "huawei_neighbor_3g",
        "huawei_neighbor_4g",
        "huawei_neighbor_4g_intra",
        "huawei_neighbor_4g_inter",
        "huawei_neighbor_export_2g",
        "huawei_neighbor_export_3g",
        "huawei_neighbor_export_4g",
    }
    if raw_table not in allowed:
        return [], 0, 0, None, "invalid raw neighbor table"

    cols = _table_columns(neighbor_conn, raw_table)
    huawei_wide = raw_table.startswith("huawei_neighbor") and not _is_slim_neighbor_table(raw_table, cols)
    rate_col: str | None = None
    if huawei_wide:
        att_col, succ_col = None, None
    else:
        att_col, succ_col = _pick_ho_metric_column(cols)

    tech_u = (technology or "").strip().upper()
    period_row = neighbor_conn.execute(
        f'SELECT MAX("_ingested_at") AS p FROM "{raw_table}"'
    ).fetchone()
    period = period_row[0] if period_row else None

    narrow_where: str | None = None
    narrow_params: list[Any] = []

    meta = sqlite3.connect(METADATA_DB, timeout=30)
    meta.row_factory = sqlite3.Row
    try:
        if tech_u.startswith("2G"):
            by_name, by_site_cell, by_cell_id = _load_2g_indexes(meta)
            if huawei_wide:
                seg_col = _pick_column(cols, "Cell_Name", "cell_name", "CELL_NAME")
                ci_col = _pick_column(
                    cols,
                    "Target_Cell_Name",
                    "target_cell_name",
                    "TARGET_CELL_NAME",
                )
                if not seg_col or not ci_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing Huawei 2G wide columns in {raw_table}: "
                        f"need Cell_Name and Target_Cell_Name (found src={seg_col!r}, tgt={ci_col!r}).",
                    )
                att_col = _pick_column(
                    cols,
                    "H370c_Outgoing_Inter_Cell_Handover_Requests",
                ) or _pick_col_norm_substrings(cols, "h370c", "outgoing", "inter", "cell", "handover")
                succ_col = _pick_column(
                    cols,
                    "H373_Successful_Outgoing_Inter_Cell_Handovers",
                ) or _pick_col_norm_substrings(cols, "h373", "successful", "outgoing", "inter", "cell")
                select_cols = [seg_col, ci_col]
                if att_col:
                    select_cols.append(att_col)
                if succ_col:
                    select_cols.append(succ_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if site_id_filter.strip() or cell_norm.strip():
                    keys = _gather_2g_export_keys_for_scope(
                        meta, vendor, site_id_filter, cell_norm
                    )
                    sc = _sql_scope_in_two_text_columns(seg_col, ci_col, keys)
                    if sc:
                        narrow_where, narrow_params = sc
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    src = by_name.get(_norm_cell_key(row[seg_col]))
                    if src and not _coord_vendor_matches(src, vendor):
                        src = None
                    tgt = by_name.get(_norm_cell_key(row[ci_col]))
                    if not tgt:
                        tgt = _resolve_2g_target(row[ci_col], by_name, by_site_cell, src.get("site_id") if src else None)
                    return src, tgt, str(row[seg_col] or ""), str(row[ci_col] or "")

            else:
                seg_col = _pick_column(
                    cols,
                    "source_cell_id",
                    "Source_Cell_ID",
                    "Segment_Name",
                    "SegmentName",
                    "segment_name",
                    "Segment",
                )
                ci_col = _pick_ci_column(cols) or _pick_column(
                    cols, "target_cell_id", "Target_Cell_ID", "Target_CI", "target_ci"
                )
                if not seg_col or not ci_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing columns in {raw_table}: need Segment Name and CI (found seg={seg_col!r}, ci={ci_col!r}).",
                    )
                if "ho_attempts" in cols:
                    att_col = "ho_attempts"
                else:
                    att_2g = _pick_2g_neighbor_attempt_column(cols)
                    if att_2g:
                        att_col = att_2g
                succ_col = None
                select_cols = [seg_col, ci_col]
                if att_col:
                    select_cols.append(att_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if _is_slim_neighbor_table(raw_table, cols) and (
                    site_id_filter.strip() or cell_norm.strip()
                ):
                    keys = _gather_2g_export_keys_for_scope(
                        meta, vendor, site_id_filter, cell_norm
                    )
                    sc = _sql_scope_in_two_text_columns(seg_col, ci_col, keys)
                    if sc:
                        narrow_where, narrow_params = sc
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    src = _lookup_2g_by_cell_id_for_vendor(row[seg_col], by_cell_id, vendor)
                    if not src:
                        cand = by_name.get(_norm_cell_key(row[seg_col]))
                        if _coord_vendor_matches(cand, vendor):
                            src = cand
                    src_site = src.get("site_id") if src else None
                    tgt = _lookup_2g_by_cell_id(row[ci_col], by_cell_id)
                    if not tgt:
                        tgt = _resolve_2g_target(row[ci_col], by_name, by_site_cell, src_site)
                    return src, tgt, str(row[seg_col] or ""), str(row[ci_col] or "")

        elif tech_u.startswith("3G"):
            by_name, by_node_cell, by_cell_id = _load_3g_indexes(meta)
            if huawei_wide:
                sc_col = _pick_column(cols, "Cell_Name", "cell_name", "CELL_NAME")
                tc_col = _pick_column(
                    cols,
                    "DEST_Cell_Name",
                    "Dest_Cell_Name",
                    "dest_cell_name",
                )
                if not sc_col or not tc_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing Huawei 3G wide columns in {raw_table}: "
                        f"need Cell_Name and DEST_Cell_Name (found sc={sc_col!r}, tc={tc_col!r}).",
                    )
                att_col = _pick_column(cols, "VS_HHO_AttOut_NCell") or _pick_col_norm_substrings(
                    cols, "vs", "hho", "attout", "ncell"
                )
                succ_col = _pick_column(cols, "VS_HHO_SuccOut_NCell") or _pick_col_norm_substrings(
                    cols, "vs", "hho", "succout", "ncell"
                )
                select_cols = [sc_col, tc_col]
                if att_col:
                    select_cols.append(att_col)
                if succ_col:
                    select_cols.append(succ_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if site_id_filter.strip() or cell_norm.strip():
                    keys = _gather_3g_export_keys_for_scope(
                        meta, vendor, site_id_filter, cell_norm
                    )
                    sc = _sql_scope_in_two_text_columns(sc_col, tc_col, keys)
                    if sc:
                        narrow_where, narrow_params = sc
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    src = by_name.get(_norm_cell_key(row[sc_col]))
                    if src and not _coord_vendor_matches(src, vendor):
                        src = None
                    tgt = by_name.get(_norm_cell_key(row[tc_col]))
                    if not tgt:
                        tgt = _resolve_3g_target(row[tc_col], by_name, by_node_cell, None, by_cell_id)
                    return src, tgt, str(row[sc_col] or ""), str(row[tc_col] or "")

            else:
                sc_col = _pick_column(
                    cols,
                    "scid_id",
                    "SCID_ID",
                    "Scid_ID",
                    "scell_id",
                    "SCell_ID",
                    "scid",
                    "SCID",
                    "source_ci",
                    "Source_CI",
                    "s_c_id",
                )
                tc_col = _pick_column(
                    cols,
                    "tcid_id",
                    "TCID_ID",
                    "Tcid_ID",
                    "target_cell_id",
                    "Target_Cell_ID",
                ) or _pick_ci_column(cols)
                if not sc_col or not tc_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing columns in {raw_table}: need scid_id (or alias) and tcid_id / CI (found sc={sc_col!r}, tc={tc_col!r}).",
                    )
                if "ho_attempts" in cols:
                    att_col = "ho_attempts"
                else:
                    att_3g = _pick_3g_neighbor_attempt_column(cols)
                    if att_3g:
                        att_col = att_3g
                if "ho_completions" in cols:
                    succ_col = "ho_completions"
                elif "ho_successes" in cols:
                    succ_col = "ho_successes"
                else:
                    compl_3g = _pick_3g_neighbor_completion_column(cols)
                    if compl_3g:
                        succ_col = compl_3g
                select_cols = [sc_col, tc_col]
                if att_col:
                    select_cols.append(att_col)
                if succ_col:
                    select_cols.append(succ_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if _is_slim_neighbor_table(raw_table, cols) and (
                    site_id_filter.strip() or cell_norm.strip()
                ):
                    keys = _gather_3g_export_keys_for_scope(
                        meta, vendor, site_id_filter, cell_norm
                    )
                    sc = _sql_scope_in_two_text_columns(sc_col, tc_col, keys)
                    if sc:
                        narrow_where, narrow_params = sc
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    src = _resolve_3g_source(row[sc_col], by_name, by_node_cell, by_cell_id, vendor)
                    src_node = src.get("site_id") if src else None
                    tgt = _resolve_3g_target(row[tc_col], by_name, by_node_cell, src_node, by_cell_id)
                    return src, tgt, str(row[sc_col] or ""), str(row[tc_col] or "")

        elif "4G" in tech_u or "LTE" in tech_u:
            is_inter_table = raw_table.endswith("_4g_inter")
            by_name, by_enb_cell = _load_4g_indexes(meta, "cells_4g_fdd")
            if huawei_wide:
                src_col = _pick_column(
                    cols,
                    "Local_cell_name",
                    "local_cell_name",
                    "LOCAL_CELL_NAME",
                )
                enb_col = _pick_column(
                    cols,
                    "Target_eNodeB_ID",
                    "Target_ENodeB_ID",
                    "target_enodeb_id",
                )
                cid_col = _pick_column(
                    cols,
                    "Target_Cell_ID",
                    "target_cell_id",
                    "TARGET_CELL_ID",
                )
                if not src_col or not enb_col or not cid_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing Huawei 4G wide columns in {raw_table}: need Local_cell_name, "
                        f"Target_eNodeB_ID, Target_Cell_ID "
                        f"(found src={src_col!r}, enb={enb_col!r}, cid={cid_col!r}).",
                    )
                att_col = _pick_column(cols, "L_HHO_NCell_ExecAttOut") or _pick_col_norm_substrings(
                    cols, "l", "hho", "ncell", "execattout"
                )
                succ_col = _pick_column(cols, "L_HHO_NCell_ExecSuccOut") or _pick_col_norm_substrings(
                    cols, "l", "hho", "ncell", "execsuccout"
                )
                rate_col = None
                select_cols = [src_col, enb_col, cid_col]
                if att_col:
                    select_cols.append(att_col)
                if succ_col:
                    select_cols.append(succ_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if site_id_filter.strip() or cell_norm.strip():
                    lns, ecs = _gather_4g_lncel_and_eci_for_scope(
                        meta, vendor, tech_u, site_id_filter, cell_norm
                    )
                    sc4 = _sql_scope_huawei_wide_4g(src_col, enb_col, cid_col, lns, ecs)
                    if sc4:
                        narrow_where, narrow_params = sc4
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    cand = by_name.get(_norm_cell_key(row[src_col]))
                    src = cand if _coord_vendor_matches(cand, vendor) else None
                    enb = _to_int(row[enb_col])
                    cid = _to_int(row[cid_col])
                    eci_val = enb * 256 + (cid % 256) if enb is not None and cid is not None else None
                    tgt = _resolve_4g_target(eci_val, by_enb_cell) if eci_val is not None else None
                    tgt_lbl = (
                        f"{row[enb_col]!s}/{row[cid_col]!s}" if enb_col and cid_col else ""
                    )
                    return src, tgt, str(row[src_col] or ""), tgt_lbl

            else:
                src_col = _pick_column(
                    cols,
                    "source_lncel_name",
                    "Source_LNCEL_name",
                    "SourceLNCELname",
                    "Source_LNCEL_Name",
                    "SourceLNCELName",
                )
                eci_col = _pick_column(
                    cols,
                    "eci_id",
                    "ECI_ID",
                    "Eci_ID",
                    "ECI",
                    "Eci",
                    "eci",
                    "Target_ECI",
                    "target_eci",
                )
                if not src_col or not eci_col:
                    return (
                        [],
                        0,
                        0,
                        period,
                        f"Missing columns in {raw_table}: need Source LNCEL name and ECI/eci_id (found src={src_col!r}, eci={eci_col!r}).",
                    )
                if "ho_attempts" in cols:
                    att_col = "ho_attempts"
                elif is_inter_table:
                    att_i = _pick_4g_inter_attempt_column(cols)
                    if att_i:
                        att_col = att_i
                else:
                    att_4g = _pick_4g_neighbor_attempt_column(cols)
                    if att_4g:
                        att_col = att_4g
                if "ho_success_rate" in cols:
                    rate_col = "ho_success_rate"
                elif is_inter_table:
                    sr_i = _pick_4g_inter_sr_column(cols)
                    if sr_i:
                        rate_col = sr_i
                else:
                    sr_4g = _pick_4g_neighbor_sr_column(cols)
                    if sr_4g:
                        rate_col = sr_4g
                if rate_col:
                    succ_col = None
                select_cols = [src_col, eci_col]
                if att_col:
                    select_cols.append(att_col)
                if succ_col:
                    select_cols.append(succ_col)
                if rate_col:
                    select_cols.append(rate_col)
                col_sql = ", ".join(f'"{c}"' for c in dict.fromkeys(select_cols))

                if _is_slim_neighbor_table(raw_table, cols) and (
                    site_id_filter.strip() or cell_norm.strip()
                ):
                    lns, ecs = _gather_4g_lncel_and_eci_for_scope(
                        meta, vendor, tech_u, site_id_filter, cell_norm
                    )
                    sc4 = _sql_scope_4g_slim(src_col, eci_col, lns, ecs)
                    if sc4:
                        narrow_where, narrow_params = sc4
                    else:
                        narrow_where, narrow_params = "0", []

                def resolve_row(row: sqlite3.Row) -> tuple[dict | None, dict | None, str, str]:
                    cand = by_name.get(_norm_cell_key(row[src_col]))
                    src = cand if _coord_vendor_matches(cand, vendor) else None
                    tgt = _resolve_4g_target(row[eci_col], by_enb_cell)
                    return src, tgt, str(row[src_col] or ""), str(row[eci_col] or "")

        else:
            return [], 0, 0, period, "unsupported technology for raw neighbor linking"
    finally:
        meta.close()

    if att_col:
        ac = str(att_col).replace('"', '""')
        if huawei_wide:
            order_hint = (
                f'COALESCE(CAST(REPLACE(REPLACE(TRIM(CAST("{ac}" AS TEXT)), ",", ""), "%", "") '
                f"AS REAL), 0) DESC"
            )
        else:
            order_hint = f'"{ac}" DESC'
    else:
        order_hint = "rowid DESC"
    scan_cap = max_scan_rows
    if narrow_where:
        scan_cap = max(max_scan_rows, max_lines * 200, 80_000)
    wh = f" WHERE ({narrow_where})" if narrow_where else ""
    sql = f'SELECT {col_sql} FROM "{raw_table}"{wh} ORDER BY {order_hint} LIMIT ?'
    rows = neighbor_conn.execute(sql, (*narrow_params, scan_cap)).fetchall()

    lines: list[dict] = []
    skipped = 0
    for row in rows:
        attempts = _to_float(row[att_col]) if att_col else 1.0
        if attempts is None:
            attempts = 0.0
        if attempts <= 0:
            continue
        if not failures_only and attempts < min_attempts:
            continue
        src, tgt, src_label, tgt_label = resolve_row(row)
        if not src or not tgt:
            skipped += 1
            continue
        if cell_norm:
            sn = _norm_cell_key(src.get("cell_name"))
            if sn != cell_norm:
                continue
        if site_id_filter:
            if str(src.get("site_id")) != site_id_filter and str(tgt.get("site_id")) != site_id_filter:
                continue

        successes = None
        rate = None
        if rate_col:
            rate = _normalize_ho_success_rate_percent(row[rate_col])
            if rate is None:
                continue
            if attempts > 0:
                successes = attempts * (rate / 100.0)
        elif succ_col:
            successes = _to_float(row[succ_col])
            if successes is not None and attempts > 0:
                rate = (successes / attempts) * 100.0

        failures = neighbor_ho_failures(attempts, rate, successes)
        if failures_only:
            thr = min_failures if min_failures > 1e-12 else 1e-9
            if failures is None or failures < thr - 1e-12:
                continue

        fr_pct = None
        if failures is not None and attempts > 0:
            fr_pct = (failures / float(attempts)) * 100.0

        # Use metadata cell_name for API/UI so /api/map/cells/wedge-data can match rows
        # (4G neighbor export target column is ECI; src may be LNCEL alias ≠ cell_name).
        src_disp = str(src.get("cell_name") or "").strip() or src_label
        tgt_disp = str(tgt.get("cell_name") or "").strip() or tgt_label
        src_v = str(src.get("vendor") or "").strip()
        tgt_v = str(tgt.get("vendor") or "").strip()
        src_site = src.get("site_id")
        tgt_site = tgt.get("site_id")
        is_intra = bool(str(src_site or "").strip() and str(src_site or "").strip() == str(tgt_site or "").strip())
        lines.append(
            {
                "period_start": period,
                "vendor": src_v
                or (
                    (vendor or "").strip()
                    if (vendor or "").strip() and (vendor or "").strip().lower() != "all"
                    else ""
                )
                or "Unknown",
                "target_vendor": tgt_v or None,
                "technology": technology,
                "source_cell": src_disp,
                "target_cell": tgt_disp,
                "source_site_id": src_site,
                "target_site_id": tgt_site,
                "is_intra_relation": is_intra,
                "relation_scope": "intra" if is_intra else "inter",
                "source_lat": src["lat"],
                "source_lng": src["lng"],
                "target_lat": tgt["lat"],
                "target_lng": tgt["lng"],
                "source_azimuth": src.get("azimuth"),
                "target_azimuth": tgt.get("azimuth"),
                "ho_attempts": attempts,
                "ho_successes": successes,
                "ho_success_rate": rate,
                "ho_failures": failures,
                "ho_failure_rate_percent": fr_pct,
            }
        )
        if len(lines) >= max_lines:
            break

    msg = None
    if not lines and rows:
        msg = (
            "No drawable lines from raw neighbor export: check metadata match "
            "(2G: Segment/CI vs cells_2g.cell_id; 3G: scid_id / tcid_id vs cells_3g.cell_id; 4G: LNCEL / ECI), "
            "HO attempt column, min attempts, vendor, and cell/site filters."
        )
    return lines, skipped, len(rows), period, msg
