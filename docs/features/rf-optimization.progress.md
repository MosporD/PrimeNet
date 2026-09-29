# RF Optimization Workbench — progress

Detailed dated log for this blueprint. Brief: [`rf-optimization.md`](rf-optimization.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

- 2026-08-17: added. 2026-08-19: vs operator targets.
