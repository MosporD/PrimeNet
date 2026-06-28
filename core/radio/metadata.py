"""Metadata inventory helpers for radio modules."""

from __future__ import annotations

from functools import lru_cache

from db.runtime import connect_metadata, execute_query, quote_ident
from modules.reports.metadata_helpers import _metadata_table_columns, _pick_col
from modules.sync.metadata_active_sql import PER_TABLE_ACTIVE_WHERE

from .scoring import to_float


TECH_TABLES = [
    ("cells_2g", "2G", ["site_id", "bcf id", "bts id"], ["site_name", "bcf name", "bts name"], ["frequency_band", "band", "bcch"]),
    ("cells_3g", "3G", ["site_id", "nodeb_id"], ["site_name", "nodeb_name"], ["dl_uarfcn", "uarfcn", "frequency_band"]),
    ("cells_4g_fdd", "4G-FDD", ["site_id", "enb_id_actual", "enodeb id"], ["site_name", "enb_name"], ["band", "earfcn", "frequency_band"]),
    ("cells_4g_tdd", "4G-TDD", ["site_id", "enb_id_actual", "enodeb id"], ["site_name", "enb_name"], ["band", "earfcn", "frequency_band"]),
    ("cells_5g", "5G", ["site_id", "gnb_id_actual", "gnb id"], ["site_name", "gnb_name"], ["bw", "nrarfcn", "frequency_band"]),
]


def _col_expr(col: str | None, alias: str, cast: str | None = None) -> str:
    if not col:
        return f"NULL AS {alias}"
    expr = quote_ident(col)
    if cast:
        expr = f"CAST({expr} AS {cast})"
    return f"{expr} AS {alias}"


def _safe_where(table: str) -> str:
    return PER_TABLE_ACTIVE_WHERE.get(table, "1=1")


def _inventory_union_sql(conn) -> str:
    parts: list[str] = []
    for table, tech, site_aliases, site_name_aliases, band_aliases in TECH_TABLES:
        cols = _metadata_table_columns(conn, table)
        if not cols:
            continue
        low = {str(c).strip().lower(): c for c in cols}
        cell_col = _pick_col(["cell_name", "cell name", "lncel name", "nrcel name", "wcel name", "bts name"], low)
        site_col = _pick_col(site_aliases, low)
        site_name_col = _pick_col(site_name_aliases, low)
        vendor_col = _pick_col(["vendor"], low)
        area_col = _pick_col(["area", "region", "market"], low)
        sector_col = _pick_col(["sector"], low)
        lat_col = _pick_col(["lat", "latitude"], low)
        lng_col = _pick_col(["long", "lng", "longitude"], low)
        az_col = _pick_col(["azimuth", "azimuth_deg"], low)
        mt_col = _pick_col(["mtilt", "mechanical_tilt", "mechanical tilt"], low)
        et_col = _pick_col(["etilt", "electrical_tilt", "electrical tilt"], low)
        band_col = _pick_col(band_aliases, low)
        pci_col = _pick_col(["pci", "psc", "bcch"], low)
        status_col = _pick_col(["activity_status", "status", "admin_state", "active_state", "activated"], low)
        parts.append(
            f"""
            SELECT
                {_col_expr(cell_col, "cell_name")},
                {_col_expr(site_col, "site_id")},
                {_col_expr(site_name_col, "site_name")},
                '{tech}' AS technology,
                {_col_expr(vendor_col, "vendor")},
                {_col_expr(area_col, "area")},
                {_col_expr(sector_col, "sector")},
                {_col_expr(lat_col, "latitude", "REAL")},
                {_col_expr(lng_col, "longitude", "REAL")},
                {_col_expr(az_col, "azimuth", "REAL")},
                {_col_expr(mt_col, "mechanical_tilt", "REAL")},
                {_col_expr(et_col, "electrical_tilt", "REAL")},
                {_col_expr(band_col, "frequency_band")},
                {_col_expr(pci_col, "pci")},
                {_col_expr(status_col, "status")}
            FROM {quote_ident(table)}
            WHERE {_safe_where(table)}
            """
        )
    if not parts:
        return """
            SELECT NULL AS cell_name, NULL AS site_id, NULL AS site_name, NULL AS technology,
                   NULL AS vendor, NULL AS area, NULL AS sector, NULL AS latitude, NULL AS longitude,
                   NULL AS azimuth, NULL AS mechanical_tilt, NULL AS electrical_tilt,
                   NULL AS frequency_band, NULL AS pci, NULL AS status
            WHERE 1=0
        """
    return "\nUNION ALL\n".join(parts)


@lru_cache(maxsize=1)
def list_cells() -> list[dict]:
    conn = connect_metadata()
    try:
        sql = _inventory_union_sql(conn)
        rows = [dict(r) for r in execute_query(conn, sql).fetchall()]
    finally:
        conn.close()
    out: list[dict] = []
    for row in rows:
        cell = str(row.get("cell_name") or "").strip()
        if not cell:
            continue
        item = dict(row)
        for key in ("latitude", "longitude", "azimuth", "mechanical_tilt", "electrical_tilt"):
            item[key] = to_float(item.get(key))
        item["cell_name"] = cell
        item["site_id"] = str(item.get("site_id") or "").strip()
        item["vendor"] = str(item.get("vendor") or "").strip()
        item["technology"] = str(item.get("technology") or "").strip()
        item["area"] = str(item.get("area") or "").strip()
        out.append(item)
    return out


def cell_index() -> dict[str, dict]:
    return {str(row.get("cell_name") or "").strip().lower(): row for row in list_cells()}


def enrich_cell(cell_name: str) -> dict:
    return cell_index().get(str(cell_name or "").strip().lower(), {})


def list_areas() -> list[str]:
    return sorted({str(r.get("area") or "").strip() for r in list_cells() if str(r.get("area") or "").strip()})

