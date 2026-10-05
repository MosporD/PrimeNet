# Conflict Map — progress

Detailed dated log for this blueprint. Brief: [`conflict-map.md`](conflict-map.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

## 2026-10-05 (2G BCCH co + adjacent)

- Done: 2G on Conflict Map + Conflict Report. Selectable co-channel / adjacent (±1) / both. No band filter (all L900). Same strictness profiles as 3G–5G (not the wider set). Excel + KML carry conflict type. Version V1.1.
- NEXT: Smoke `/conflict-map` 2G both modes and Reports Conflict Report download after metadata load.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

No dated rewrite in `progress.md` beyond existing map.
