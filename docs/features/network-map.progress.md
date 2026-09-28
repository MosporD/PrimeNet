# Network Map — progress

Detailed dated log for this blueprint. Brief: [`network-map.md`](network-map.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-09-28 — Per-user KMZ layers

- Upload `.kmz`/`.kml` from left filter panel; files + GeoJSON stored under `uploads/network_map_kmz/{user_id}/`; metadata in `map_user_layers`.
- Google Earth-style folder/placemark checkbox tree; visibility persisted; Leaflet overlay for points/lines/polygons.
- APIs: `GET/POST /api/map/layers`, `GET …/geojson`, `PATCH …/visibility`, `DELETE …/<id>`.
- Helper: `modules/network_map/kmz_layers.py`. GroundOverlay / NetworkLink skipped with upload warning.

**NEXT:** Smoke on Network Map — upload a real planning KMZ, toggle folders, reload page (visibility + geometry should stick).

---
## From brief History (migrated 2026-09-17)

Map is a long-lived heavy module (Lesson 08). Neighbor Excel (2026-08-31) is on the analysis page, not this one.
