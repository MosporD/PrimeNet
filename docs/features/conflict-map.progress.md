# Conflict Map — progress

Detailed dated log for this blueprint. Brief: [`conflict-map.md`](conflict-map.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

## 2026-10-06 (Distance only strictness)

- Done: New strictness profile `distance` — azimuth ignored; High ≤4 km, Medium to midpoint, Low within 6 km. Map + Conflict Report. Version V1.2.
- NEXT: Smoke Distance only on `/conflict-map` vs Standard for the same PCI/BCCH.

## 2026-10-05 (active-only study)

- Done: Conflict pairs use on-air cells only (`PER_TABLE_ACTIVE_WHERE` / vendor active_state·admin_state). Dropped null/empty status pass-through that was letting Inactive 2G/3G/4G/5G into the pool.
- NEXT: Refresh conflict cache on `/conflict-map` and confirm pair counts drop vs previous Inactive-heavy runs.

## 2026-10-05 (2G BCCH co + adjacent)

- Done: 2G on Conflict Map + Conflict Report. Selectable co-channel / adjacent (±1) / both. No band filter (all L900). Same strictness profiles as 3G–5G (not the wider set). Excel + KML carry conflict type. Version V1.1.
- NEXT: Smoke `/conflict-map` 2G both modes and Reports Conflict Report download after metadata load.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

No dated rewrite in `progress.md` beyond existing map.
