# Adjacency GIS — progress

## Current track

BCCH adjacent-channel highlighter on the 2G metadata map. CM NCL overlay later.

## NEXT

Open `/adjacency-gis`: basemap list top-right (always open), BCCH panel bottom-right, no saved views. When CM pipeline is ready, overlay ADCE / G2GNCELL edges.

## 2026-10-04 (BCCH / basemap chrome split)

- Done: Removed saved views. BCCH adjacent-channel panel is its own bottom-right float. Basemap selection is the Leaflet layers control top-right, always expanded (not auto-collapsible). Version V1.7.
- NEXT: Smoke layout in light + dark; confirm BCCH highlight still paints wedges.

## 2026-10-04 (Filter float + tech chip parity)

- Done: Matched Network Map filter treatment — collapsible floating Filters card over the map; Soft Steel instrument tech chip (stacked label/count, swatch, radiogroup); site info as bottom float; dark-mode parity. Kept Adjacency-only controls (basemap, activity, BCCH block). Version V1.6.
- NEXT: Smoke BCCH highlight + collapse persistence after hard refresh.

## 2026-09-24 (Basemap switcher)

- Left-panel **Map view** select: Roadmap (default) / Street / HOT / Topo / Satellite / Terrain.
- Choice persisted in `localStorage`; synced with Leaflet layers control + saved views.
- Version bump V1.4.

## 2026-09-24 (BCCH adjacent-channel highlighter)

- APIs: `bcch-options`, `bcch-map` from `cells_2g`.
- UI: dropdown + Prev/Next; selected red, −1 blue, +1 green wedge overlay.
- Default basemap Roadmap (Esri World Street Map).
- Missing neighbors still out of scope.

## 2026-09-23 (UI fork from Network Map)

- Replaced custom snapshot map UI with Network Map copy (template / CSS / JS).
- Locked to 2G from `metadata.db` via `/api/map/*`; auto-loads on open.
- Dropped repeaters from this page; CM ingest APIs kept for Admin / future NCL.

## 2026-09-20 (Dark mode)

- Done: `body.dark-mode.adjacency-gis-page` filter-panel rules + shared `theme-dark-final.css` safety net.

## 2026-09-20 (Huawei CM ingest)

- Huawei: `LST GCELL` + `LST GTRX` (main BCCH) + `LST G2GNCELL`; per-vendor snapshot store.
- Scheduler: Nokia **04:30**, Huawei **04:45**; Admin buttons for Nokia / Huawei / both.
- Map vendor filter; catalog MOs GTRX + G2GNCELL; tests for huawei_parse + multi-vendor store.

## 2026-09-20

- Scaffolded `modules/adjacency_gis/` (routes, logic, store, nokia_parse, ingest_job, Leaflet UI).
- Wired: `primenet_app`, NAV, versions, dashboard tile, scheduler cron, Admin status/run APIs.
- Audits: unidirectional, overshoot (default 15 km), NCL > 32, co-channel.
- Tests: `test_nokia_parse`, `test_logic`, `test_store`.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

