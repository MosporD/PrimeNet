# Neighbor Analysis

Map of neighbor relations (HO attempts) + Excel export. **Not** Neighbor Quality.

| | |
|---|---|
| Route | `/neighbor-analysis` |
| Same blueprint | `modules/network_map/` |
| Linking | `neighbor_raw_linking.py` |
| DBs | `NEIGHBOR_KPI_DB`, `HUAWEI_NEIGHBOR_RAW_DB` via `open_db` |
| Access | all |
| Version | V1.0 |

## Purpose

Draw neighbor lines for a drawn cell/site scope. Export the same filtered rows to Excel.

## Approach

- Lines payload: `_fetch_neighbor_lines_payload()`. Export: `GET /api/network-map/neighbors/export` + `core/table_excel_export.py`.
- Empty scope → **400**, not a blank xlsx.
- Loaders: `scripts/load_nokia_neighbor_raw_to_db.py`, `scripts/load_huawei_neighbor_wide_to_db.py`.
- Do not change Neighbor Quality (`/neighbor-quality`) when the request is this map.

## History

- 2026-08-17: 5G-5G + azimuth/freshness.
- 2026-08-31: Export Excel on the analysis page; JS `||` for Content-Disposition (not Python `or`).

## Plans

Live DB often returns 0 lines until a cell is drawn — that is expected. SON Topology needs a **ML rebuild** after `NEIGHBOR_MAX_LINES=100000` (that cap is in the quality/SON path, not this Excel button).

## Watch-outs

Huawei 2G wide columns are picky (`Cell_Name` / `Target_Cell_Name`). Linking rules are documented at the top of `neighbor_raw_linking.py`.
