# Radio Hardware Inventory Report — progress

Detailed dated log for this blueprint. Brief: [`rru-inventory.md`](rru-inventory.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Current track:** Hardware tab of Configuration Dashboard (engine V1.2)

**NEXT:** None parked — use `/configuration-dashboard?tab=hardware`; shared ingest also pulls WNCELG.

---
## 2026-09-20 (Moved under Configuration Dashboard)

- Product surface: Hardware tab of `/configuration-dashboard`; `/rru-inventory` redirects.
- Ingest: shared job with WNCELG (same 04:00 / Admin trigger).

## From brief History (migrated 2026-09-17)

- 2026-09-17: V1.2 snapshot-only UI areas; 3G/4G band nodes; All-areas network Sankey.
- 2026-09-17: V1.1 daily 04:00 snapshot + admin manual run + Excel export; UI reads DB.
- 2026-09-17: V1.0 Area → Tech → productName Sankey + unused/tech filters.

## 2026-09-17 (RRU Inventory — snapshot-only + bands)

- Done: Areas API from snapshot DB only (Load never hits NetAct).
- Done: 3G/4G band fan-out via metadata (`4G-L18`/`L18new`/`L9`/`L21`, `3G-U2100`); All-areas = Tech→RRU.
- Smoke on existing snapshot: L18new 4944, L18 4550, U2100 3785, …
- Tests: `test_logic` + `test_store` + `test_band_map` — 16 passed.

## 2026-09-17 (RMOD list-param fix)

- Root cause: NetAct rejects `@active*CellsList` (scalar required) — StructuredValue/list.
- Done: Ingest lists DNs via `dn()` / queryMOLites, then `getManagedObjects` for full params incl. cell lists.
- Tests: managed-object list emptiness + tech mapping.

## 2026-09-17 (Radio Hardware Inventory — daily snapshot)

- Done: SQLite snapshot store; scheduler cron **04:00**; Admin manual run (`/api/admin/rru-inventory/run`).
- Done: Module UI reads snapshot (not live); Excel download; status pill for last build.
- Tests: `test_logic` + `test_store` — 9 passed.

## 2026-09-17 (Radio Hardware Inventory Report — RMOD_R)

- Done: New module `/rru-inventory` (display name **Radio Hardware Inventory Report**) — live Nokia `RMOD_R`, Area → Tech → `productName` Sankey (D3 vendored).
- Tech from `activeGsm/Wcdma/Lte/NrCellsList`; unused (all empty) filterable in UI; multi-RAT fans out per tech.
- Wired: `primenet_app`, `module_access`, `module_versions`, dashboard card, feature brief.
- Tests: `modules/rru_inventory/test_logic.py` — 7 passed. Live NetAct not configured on laptop.
