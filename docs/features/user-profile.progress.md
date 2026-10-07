# User Profile — progress

Detailed dated log for this blueprint. Brief: [`user-profile.md`](user-profile.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---

## 2026-10-05 (CM Approver status)

- Done: Profile avatar card shows read-only **CM Approver** Yes/No from `can_approve` (Owners always Yes). Assignment stays in Platform Admin.

## 2026-10-07 (CM Live Write label)

- Done: Profile shows **CM Live Write** Yes/No; tooltip points to Engineering Admin → CM Live Write.
- NEXT: None for this slice.

---
## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

Phase 1 app-DB callers (2026-08-31). Vendor creds module `core/user_vendor_credentials.py`.
