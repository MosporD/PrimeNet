# Adjacency GIS

2G Network Map fork — sites/sectors from `metadata.db`, plus BCCH adjacent-channel highlighter.

| | |
|---|---|
| Route | `/adjacency-gis` |
| Module | `modules/adjacency_gis/` |
| Access | all |
| Version | V1.4 |

## Purpose

Geographic 2G picture for adjacency / NCL work. Geometry from `metadata.db` `cells_2g`. BCCH highlighter paints co-channel reuse (selected) and ±1 adjacent ARFCNs. Configured NCL audits (Nokia ADCE / Huawei G2GNCELL) stay behind Admin ingest until that pipeline overlays.

## Approach

- UI: Network Map fork (Leaflet, left filter panel, wedges) locked to **2G**; default basemap **Roadmap**, switchable via left-panel **Map view** (Street / HOT / Topo / Satellite / Terrain) + Leaflet layers control.
- Sites: Network Map `/api/map/*` with client `tech=2G`.
- BCCH overlay: `/api/adjacency-gis/bcch-options` + `/api/adjacency-gis/bcch-map` against `cells_2g.bcch` — selected red, ARFCN−1 blue, ARFCN+1 green; Prev/Next steps integer ARFCN.
- CM snapshot store + ingest retained for future NCL edges.
- Missing/phantom neighbor detection not in scope yet.

## Progress

Dated work log: [`adjacency-gis.progress.md`](adjacency-gis.progress.md).

## Plans

None parked.

## Watch-outs

Do not fold into Network Map without an explicit ask. Band dropdown (`frequency_band`) is not BCCH — use the dedicated BCCH control.
