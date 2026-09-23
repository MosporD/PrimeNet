# RET Management

Remote electrical tilt read/propose.

| | |
|---|---|
| Route | `/ret-management` |
| Module | `modules/ret_management/` (`logic.py`, `site_layout.py`, `test_logic.py`, `test_site_layout.py`) |
| Access | all |
| Version | V1.2 |

## Purpose

Antenna RET values. Unit tests in `test_logic.py` / `test_site_layout.py` — read those first.

## Approach

Treat tests as spec. Live writes to OSS follow the same confirmation culture as CM reimport — do not add silent push.

Sector → hologram join:
- Huawei `RETSUBUNIT.Subunit Name`: `{SiteId}_{Sector}-…` (e.g. `1020_A-2G-L900`) — first two parts only; no Actual Sector ID / subunit fallbacks.
- Nokia `RETU_R.sectorID`: `D4-L1800` or `F1_F2-A1-3G-L1800-L2100`; site from `baseStationID`.
- Canonical key via `normalize_sector_key` (inventory `1003_A` → `1`). Azimuth from `metadata.db` `cells_*` (preferred over Nokia `antBearing`).
- Tech from CM name truth table via `infer_ret_tech_from_label` (not inventory RAT assumptions).
- Hologram: vendored three.js, 30° default perspective, 60° HPBW 3D lobes.

## Progress

Dated work log: [`ret-management.progress.md`](ret-management.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

RET is mechanical/electrical tilt, not load balancing.
`three.min.js` is vendored under `static/vendor/` for intranet (no CDN).
