# Adjacency GIS

2G Network Map fork — sites/sectors from `metadata.db` until CM NCL pipeline is primary.

| | |
|---|---|
| Route | `/adjacency-gis` |
| Module | `modules/adjacency_gis/` |
| Access | all |
| Version | V1.2 |

## Purpose

Geographic 2G picture (same UX as Network Map) for adjacency / NCL work. Geometry today comes from `metadata.db` `cells_2g`. Configured NCL audits (Nokia ADCE / Huawei G2GNCELL) stay behind Admin ingest until that pipeline is ready to overlay.

## Approach

- UI: copy of Network Map (Leaflet, left filter panel, wedges, search, polygon export) locked to **2G**.
- Data: Network Map `/api/map/*` against `connect_metadata()`; client forces `tech=2G`.
- CM snapshot store + ingest (`store.py`, `ingest_job.py`, Admin buttons) retained for future NCL edges — not required to open the map.
- Separate from Neighbor Analysis (`/neighbor-analysis` HO lines).

## Progress

Dated work log: [`adjacency-gis.progress.md`](adjacency-gis.progress.md).

## Plans

None parked.

## Watch-outs

Do not fold into Network Map without an explicit ask. When CM pipeline lands, overlay edges on this UI rather than reverting to the old custom filter panel.
