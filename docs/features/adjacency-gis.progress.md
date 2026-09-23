# Adjacency GIS — progress

## Current track

2G Network Map UI fork on `metadata.db` (looks / filters first). CM NCL overlay later.

## NEXT

Confirm 2G map look on `/adjacency-gis` (sites, wedges, BCCH band filter). When CM pipeline is ready, overlay ADCE / G2GNCELL edges on this shell.

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
