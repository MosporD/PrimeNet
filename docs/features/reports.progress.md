# Performance Reports — progress

Detailed dated log for this blueprint. Brief: [`reports.md`](reports.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

## 2026-10-06 (Unified report settings panels)

- Done: Site Inventory, Conflict Report, and Sector Health all open a settings panel then Generate. Sector Health + Sector Health (All Cells) merged into one card with Active-only / All cells scope. `sector_health_all` kept for generate + archive. Version V1.6.
- NEXT: Smoke Site Inventory tech filter + Sector Health Active vs All from the single card.

---
## 2026-10-06 (Conflict Report settings UI)

- Done: Conflict Report opens settings (tech, 2G mode, optional distance km, optional azimuth 1–180 both sides). Empty = ignore. Generate button. Removed fixed dual BCCH pack / strictness dropdown from Reports.
- NEXT: Smoke generate with distance-only, azimuth-only, and both.

---
## 2026-10-06 (BCCH dual report)

- Superseded same day by Conflict Report settings UI (distance + azimuth inputs).

---
## 2026-10-05 (Conflict Report 2G BCCH)

- Done: Conflict Report tech includes 2G; conflict-type selector (co / adjacent / both) when 2G. Same strictness profiles as Conflict Map (shared with 3G–5G).
- NEXT: Smoke Excel download for 2G both modes.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## 2026-09-23

- Done: Sector Health Vendor labels — Huawei / Nokia Thin (FDD split) vs Huawei TDD / Nokia; All Cells Active/Inactive per layer. Version V1.3.
- **NEXT:** Spot-check regenerated Excel Thin / TDD-Nokia samples.

## From brief History (migrated 2026-09-17)

- 2026-08-19: Sector Health / Excel matrix coverage = metadata only.
- Last-insert unified for app Postgres (2026-08-31 phase 1).
