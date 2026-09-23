# Adjacency GIS

2G configured NCL GIS auditor — Nokia ADCE + Huawei G2GNCELL.

| | |
|---|---|
| Route | `/adjacency-gis` |
| Module | `modules/adjacency_gis/` |
| Access | all |
| Version | V1.1 |

## Purpose

Visually audit GSM neighbor cell lists from **configuration** (not HO PM). Catch unidirectional links, NCL overflow (>32), long overshoot neighbors, and co-channel clashes.

## Approach

- Per-vendor snapshot store + scheduled CM ingest (Nokia NetAct Open API; Huawei U2020 MML).
- Geometry from `metadata.db` `cells_2g` (lat/long/azimuth) joined by cell name / CI.
- Nokia: `channel0Type == 4` → BCCH; `initialFrequency`; skip locked `adminState`; edges from **ADCE**.
- Huawei: `LST GTRX` (`Is Main BCCH TRX` + Frequency + admin/active); `LST GCELL` for names; edges from **G2GNCELL**.
- Separate from Neighbor Analysis (`/neighbor-analysis` HO lines).

## Progress

Dated work log: [`adjacency-gis.progress.md`](adjacency-gis.progress.md).

## Plans

None parked.

## Watch-outs

NetAct Open API can return empty GSM trees on some BSCs. Huawei BSC NE names must resolve via discovery/metadata. Do not fold into Network Map / Neighbor Analysis without an explicit ask.
