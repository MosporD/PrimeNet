# Admin Panel — progress

Detailed dated log for this blueprint. Brief: [admin-panel.md](admin-panel.md).
Root journal (topics only): [../../progress.md](../../progress.md).

---
## 2026-09-29 (ETL Diagnosis UI stability)

- Done: Fingerprint-gated poll (10s), in-place progress cards, clamp meta text — stops blink from full DOM rewrite.
- Done: Contain `etl-two-col` (`minmax(0,1fr)` + overflow) so Scheduler jobs / Last OK stay inside the card.
- Done: Eng Admin `--ui-zoom: 1.5`; clearer scheduler-not-in-web copy (cron lives in scheduler container).
- NEXT: Confirm scheduler container on 97.141 (`docker compose ps/logs scheduler`); re-run Daily after `%%` LIKE adapter deploy.

## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). PM surveys + ETL diagnosis use `list_tables` / `store_available`; UI domain fallback is Postgres-oriented.
- NEXT: Smoke primary routes after Daily load on server PG.

## 2026-09-28 (ETL Diagnosis page)

- Done: Engineering Admin tab **ETL Diagnosis** (`?section=etl-diagnosis`) — live progress, manual pipeline ops, PG domain/store counts, sync_log feed, alerts (lock storm, ETL gate, reset mode, meta/pm mismatch).
- Done: APIs `GET /api/sync/diagnosis`, `POST /api/sync/trigger/{hourly_full,daily_full,neighbor_sync}`; orchestrator progress keys; daily metadata scheduler job restored.
- NEXT: After server deploy, restart scheduler and open `/admin-panel?section=etl-diagnosis` to clear lock storm + trigger metadata.

## 2026-09-23 (No Platform Admin chrome)

- Done: Dropped Platform Admin header link; use NexusCore portals topbar Admin only.

## 2026-09-23 (Ops-only Engineering Admin)

- Done: Removed User Administration and Feature Access from PrimeNet Admin (moved to NexusCore Platform Admin).
- Done: Owner-only Engineering Admin; Ops Alerts tab keeps RET/CM accountability panels.
- Done: Nav/dashboard → Eng Admin (`?section=data-sync`).
- NEXT: None parked.

## 2026-09-20 (Portal allow-list on users)

- Done: Create-user portal checkboxes; Users table Portals column; PUT /api/admin/users/<id>/portals.
- NEXT: Bulk-grant NexPulse to marketing operators who should keep access after SSO cutover.

## From brief History (migrated 2026-09-17)

Activity log / feature grants evolved with the radio pack (2026-08).
2026-09-11: PM Plus Rules tab — family/counter agg + catalog import under /api/admin/pm-plus/*.
2026-09-17: CM Extractor Activity panel + Activity Log category filter (cm_* actions).
