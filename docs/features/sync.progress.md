# Sync / pipeline (ETL) — progress

Detailed dated log for this blueprint. Brief: [`sync.md`](sync.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Local ETL kill switch remains `NCM_ENABLE_ETL=0` on laptop.

---
## From brief History (migrated 2026-09-17)

- 2026-09-11: `NCM_ENABLE_ETL` gate + local ETL data cleanup script.
- 2026-08-02: scheduler RAM isolation.
- 2026-08-31: ingest paths wired through `open_db` for optional Postgres.

## 2026-09-11 (ETL gate + local cleanup)

- Done: `core/etl_gate.py` — `NCM_ENABLE_ETL=0/1` master switch (loads `.env`); wired into bootstrap, scheduler, sync triggers, pipeline orchestrators/pull/load, PM Plus workers.
- Done: Local `.env` + `.env.example` set `NCM_ENABLE_ETL=0`; server scheduler entrypoint defaults to `1`.
- Done: `scripts/clear_local_etl_data.py` — wipes PM/raw/sync_downloads, keeps admin+metadata+geo.
