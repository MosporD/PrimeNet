# Elevation

Terrain elevation lookups (overshooting / LOS helpers).

| | |
|---|---|
| Route | `/elevation` (API-style module) |
| Module | `modules/elevation/` |
| Core | `core/elevation.py` |
| Access | all |
| Cache | `elevation_cache` in app DB; extra geo sqlite under `databases/geo/` |

## Purpose

Height samples for radio geometry. Not a dashboard constellation tile.

## Approach

Cache aggressively. `databases/geo/elevation_cache.db` stays SQLite (not a PG domain). App-table cache is `elevation_cache` via `connect_app()`.

## Progress

Dated work log: [`elevation.progress.md`](elevation.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked. Do not pull a new global DEM without asking.
