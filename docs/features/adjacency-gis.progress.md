# Adjacency GIS — progress

## Current track

Nokia + Huawei scheduled CM snapshots + Leaflet map audits.

## NEXT

Admin → Data Sync → run Nokia / Huawei adjacency ingest against live CM; verify both vendors on `/adjacency-gis`; spot-check dark toggle on filter panel.

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
