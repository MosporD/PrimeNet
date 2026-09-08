# Sector Health

Per-sector rollups. Two pages, one blueprint.

| | |
|---|---|
| Routes | `/sector-health`, `/sector-health-all` |
| Module | `modules/sector_health/` |
| Access | all |
| Version | V1.3 |

## Purpose

Monitored sectors vs all configured cells. Coverage = metadata (active vs all), **not** Sleeping Cells PM.

## Approach

Do not overlay sleeping-cell PM on this matrix. Shared radio TTL cache applies to expensive scans (`?refresh=1`).

## History

- 2026-09-08: Stopped excluding Nokia `2G / GSM 900` (and sparse DCS labels) from the coverage matrix — that zeroed Nokia 2G sector counts. Normalize to `2G / GSM900`. Version V1.3.
- 2026-08-19: Sleeping Cells overlay removed from Sector Health / Excel matrix. Version V1.2.

## Plans

None parked.

## Watch-outs

Two hrefs in `NAV_SECTIONS` / `module_versions` (`sector-health` and `sector-health-all`).
