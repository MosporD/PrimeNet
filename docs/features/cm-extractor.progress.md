# Configuration Data Extractor — progress

Detailed dated log for this blueprint. Brief: [`cm-extractor.md`](cm-extractor.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

Long-lived. Job scheduler uses `connect_app()` (2026-08-31). Sample Huawei workbook under `uploads/cm_extractor/samples/`.
2026-09-17: Guard East Amman-scale neighbor extracts; dictionary MO technology for LTE filtering; richer `activity_log` for CM extract start/success/fail (Admin → User Admin + Activity Log filter).

## 2026-09-17 (CM Extract — East Amman neighbor + admin logging)

- Root cause: East Amman Huawei 4G ≈220 eNodeBs; `CELL` is fine area-wide, but `EUTRANINTERFREQNCELL` is high-cardinality and overwhelms U2020 MML / timeouts.
- Done: Refuse neighbor/relation MOs above 40 NEs with a clear error; smaller MML chunks (10) for those MOs; dictionary MO technology for LTE NE filtering.
- Done: CM extract activity logging (`cm_extract_start` / success / fail / async / download) + Admin User Admin panel + Activity Log action filter.
- Tests: `core/cm_extractor/test_huawei_controller_scope.py` extended.

## 2026-09-08 (dark-mode UI fixes)

- Done: Cell Heatmap status text, Femto Create KPI button, SON header (no READ-ONLY, standard topbar), CM Extractor scrollbars, Parameter Audit golden-rules panel, XML Parser plan validation, Overshooting/radio-module opaque dark background.
- Deploy note: server must `git pull` to `a575aeba+` then rebuild; these fixes are local until pushed.

## 2026-08-05

- Done: SMB auto-mount for Network Balance on Linux Docker
- Done: Performance chart layouts, search deep links, RET writes, admin activity
- Done: Huawei HedEx in-page TOC links
- Done: Nokia NE list site-ID resolution cache
- Modified: `deploy/`, `docker-compose.yml`, `core/cm_extractor/nokia_discovery.py`, `modules/performance/`, `modules/ret_management/`, `modules/ran_features/hdx.py`
