# Network Map — progress

Detailed dated log for this blueprint. Brief: [`network-map.md`](network-map.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-10-04 (Tech filter selection polish)

- Done: Tech chips → instrument single-select grid: stacked label/count, tech swatch, Soft Steel selected state (not full-bleed fill), radiogroup semantics, dark-mode parity.
- NEXT: Smoke on Network Map — upload a real planning KMZ, toggle folders, reload page (visibility + geometry should stick).

## 2026-09-29 (Postgres-only)

- How it works on PG: metadata + neighbor stores via `open_db` / `connect_metadata`; table probes use `table_exists` (adapter → `information_schema`). Map 500s after Daily failure were empty/missing metadata tables plus catalog SQL against PG — fix depends on successful Daily load + existence rewrite.
- NEXT: After Daily load on PG, re-check `/api/map/sites?tech=2G|3G` and cell-code search.

## 2026-09-28 — Per-user KMZ layers

- Upload `.kmz`/`.kml` from left filter panel; files + GeoJSON stored under `uploads/network_map_kmz/{user_id}/`; metadata in `map_user_layers`.
- Google Earth-style folder/placemark checkbox tree; visibility persisted; Leaflet overlay for points/lines/polygons.
- APIs: `GET/POST /api/map/layers`, `GET …/geojson`, `PATCH …/visibility`, `DELETE …/<id>`.
- Helper: `modules/network_map/kmz_layers.py`. GroundOverlay / NetworkLink skipped with upload warning.

**NEXT:** Smoke on Network Map — upload a real planning KMZ, toggle folders, reload page (visibility + geometry should stick).

---
## From brief History (migrated 2026-09-17)

Map is a long-lived heavy module (Lesson 08). Neighbor Excel (2026-08-31) is on the analysis page, not this one.
