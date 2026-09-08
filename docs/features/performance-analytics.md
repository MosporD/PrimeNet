# Huawei PM Query Studio

Ad-hoc Huawei PM querying (admin).

| | |
|---|---|
| Route | `/performance-analytics` |
| Module | `modules/performance_analytics/` |
| Access | admin |
| Version | V1.0 |

## Purpose

Studio UI for Huawei PM tables beyond the main Explorer presets.

## Approach

Reuse Explorer/PM helpers where possible. Do not duplicate Nokia paths here — this tile is Huawei-oriented. Admin-only; keep it that way unless Malek asks.

## History

Shipped as admin studio. No dated rewrite in `progress.md`.

## Plans

None parked.

## Watch-outs

Easy to confuse with `/performance` (all-vendor Explorer) and `/performance-dictionary` (counter reference).
