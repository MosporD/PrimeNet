# RET Management — progress

Detailed dated log for this blueprint. Brief: [`ret-management.md`](ret-management.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Hologram polish browser smoke; ground reach from performance/TA (needs per-cell PM + RET↔cell map) — geometric h/tan(tilt) clamped 100–1000 m for now.

**NEXT:** Browser smoke hologram after hard-refresh.

---
## From brief History (migrated 2026-09-17)

- 2026-09-17: Band-scaled lobe reach (L900>L1800>L2100); AAU Left/Right 30° half-beams; RET downtilt drives 3D; site cabin + N/S/E/W compass; stage +50%.
- 2026-09-17: RET label truth table (2G/3G/4G/4G-TDD/4G-AAU-*/4G-L1800+/Not Used; layer digits 1–4); per-tech lobe toggles; mesh wireframe lobes.
- 2026-09-16: Sector parsers aligned to live CM name forms; metadata `site_Letter` key fix; three.js 3D hologram (60° HPBW lobes, 30° tilt).
- 2026-08-05: RET writes mentioned with admin activity.

## 2026-09-17 (Hologram coverage realism)

- Done: Lobe length from RET downtilt (° below horizon) × band tier (2G/L900 > L1800/L1800+ > L2100/3G).
- Done: AAU Left/Right → 30° HPBW half-beams at ±15° from sector azimuth.
- Done: Rectangular site cabin + headframe + panels; N/S/E/W compass; canvas ~+50%.
- Load RET / table edits rebuild hologram from degrees.

## 2026-09-17 (RET label truth table)

- Done: `infer_ret_tech_from_label` is the only RET→tech mapper (Nokia `sectorID` / Huawei `Subunit Name`).
- Mapping: 2G; 3G; 4G/4G2→4G; LTE+TDD→4G-TDD; AAU+Left/Right→4G-AAU-*; Capacity→4G-L1800+; F#→3G; Band→4G; Letter+digit layers 1→4G/2→2G/3→3G/4→4G-L1800+; NA→Not Used.
- Hologram `TECH_COLORS` / `TECH_ORDER` updated for the new keys (metadata 4G-FDD/5G kept as fallback).
- Tests: 43 passed in ret_management logic/site_layout.

## 2026-09-17 (RET hologram — per-tech toggles + mesh lobes)

- Done: `_ret_tech` from Huawei `Subunit Name` / Nokia `sectorID`.
- Done: One hologram lobe per sector×tech; rail toggles All/None/per-tech.
- Done: Wireframe mesh envelope (reference-style) instead of smooth filled surface.
- Tests: ret_management logic/site_layout.

## 2026-09-16 (RET Management smoke — Nokia 1003 / Huawei 1020)

- Done: Restarted PrimeNet on :8001 with new templates; `scripts/_smoke_ret_management.py` green.
- UI: page + `three.min.js` + hologram assets OK; pitch default 30°.
- Nokia site `51003`/`1003`: layout 3 lobes @ 50/150/340; 18 RETU rows → 12 mapped (A/B/C forms), 6 unmapped empty `sectorID`, 0 orphans.
- Huawei site `1020`: layout 3 lobes @ 60/190/320; 12/12 RETSUBUNIT mapped from `1020_{A|B|C}-…`.
- Fix: unreadable personal vendor ciphertext now falls back to shared CM account (was hard 400).

## 2026-09-16 (RET Management — sector join + 3D hologram)

- Done: Huawei sector from `Subunit Name` form `{SiteId}_{Sector}-…` only (no Actual Sector ID / subunit fallbacks).
- Done: Nokia sector from `sectorID` forms `D4-L1800` / `F1_F2-A1-3G-…`; site from `baseStationID`.
- Done: `normalize_sector_key` treats metadata `1003_A` as sector A→1 (was collapsing whole site).
- Done: Hologram prefers metadata azimuth; three.js 3D mast + cos^n lobes (60° HPBW), default 30° camera tilt; `three.min.js` vendored.
- Tests: `modules/ret_management/test_logic.py` + `test_site_layout.py` — 41 passed.

## 2026-08-05

- Done: SMB auto-mount for Network Balance on Linux Docker
- Done: Performance chart layouts, search deep links, RET writes, admin activity
- Done: Huawei HedEx in-page TOC links
- Done: Nokia NE list site-ID resolution cache
- Modified: `deploy/`, `docker-compose.yml`, `core/cm_extractor/nokia_discovery.py`, `modules/performance/`, `modules/ret_management/`, `modules/ran_features/hdx.py`
