# Huawei PM Query Studio — progress

Detailed dated log for this blueprint. Brief: [`performance-analytics.md`](performance-analytics.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

Shipped as admin studio. No dated rewrite in `progress.md`.
