# Layer Coverage Gaps — progress

Detailed dated log for this blueprint. Brief: [`layer-coverage.md`](layer-coverage.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

- 2026-08-17 / 2026-08-19: pack + targets.
