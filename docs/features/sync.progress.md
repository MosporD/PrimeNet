# Sync / pipeline (ETL) — progress

Detailed dated log for this blueprint. Brief: [`sync.md`](sync.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Local ETL kill switch remains `NCM_ENABLE_ETL=0` on laptop.

---
## 2026-09-29 (No PM after cutover — diagnosis)

- State: all `pm_*` hourly tables still 0 rows; metadata RAT tables populated; daily schemas empty.
- Causes: `NCM_SYNC_RESET_MODE` default was parked (fixed → opt-in); scheduler pipeline lock still stuck (restart); daily/hourly failures had opaque `code=1` (now include stderr detail).
- NEXT: Server set `NCM_SYNC_RESET_MODE=0` (or omit), restart scheduler, redeploy, re-run hourly/daily from ETL Diagnosis.

- Done: `modules/sync/etl_diagnosis.py` + `/api/sync/diagnosis`; progress for hourly/daily/neighbor/category jobs; triggers for hourly_full / daily_full / neighbor_sync.
- Done: Re-registered daily `pull_metadata` cron (`METADATA_PULL_HOUR` / `METADATA_PULL_MINUTE`, default daily pull hour :20). Kill switch `NCM_DISABLE_METADATA_SCHEDULER=1`.
- NEXT: Server rebuild/restart scheduler; confirm `NCM_SYNC_RESET_MODE=0` and `pm` in `NCM_PG_DOMAINS` (or unset domains).

## From brief History (migrated 2026-09-17)

- 2026-09-11: `NCM_ENABLE_ETL` gate + local ETL data cleanup script.
- 2026-08-02: scheduler RAM isolation.
- 2026-08-31: ingest paths wired through `open_db` for optional Postgres.

## 2026-09-11 (ETL gate + local cleanup)

- Done: `core/etl_gate.py` — `NCM_ENABLE_ETL=0/1` master switch (loads `.env`); wired into bootstrap, scheduler, sync triggers, pipeline orchestrators/pull/load, PM Plus workers.
- Done: Local `.env` + `.env.example` set `NCM_ENABLE_ETL=0`; server scheduler entrypoint defaults to `1`.
- Done: `scripts/clear_local_etl_data.py` — wipes PM/raw/sync_downloads, keeps admin+metadata+geo.
