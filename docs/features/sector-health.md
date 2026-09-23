# Sector Health

Per-sector rollups. Two pages, one blueprint.

| | |
|---|---|
| Routes | `/sector-health`, `/sector-health-all` |
| Module | `modules/sector_health/` |
| Access | all |
| Version | V1.5 |

## Purpose

Monitored sectors vs all configured cells. Coverage = metadata (active vs all), **not** Sleeping Cells PM.
All-cells Excel marks each layer **Active** / **Inactive**. Vendor column uses mix labels:
**Huawei / Nokia Thin** (FDD split, no Huawei TDD), **Huawei TDD / Nokia Thin** (FDD split + Huawei TDD),
and **Huawei TDD / Nokia** (Huawei L35 + Nokia, FDD not split).
FDD completeness remains the four layers L18 / L18+ / L9 / L21.

## Approach

Do not overlay sleeping-cell PM on this matrix. Shared radio TTL cache applies to expensive scans (`?refresh=1`).

## Progress

Dated work log: [`sector-health.progress.md`](sector-health.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

Two hrefs in `NAV_SECTIONS` / `module_versions` (`sector-health` and `sector-health-all`).
