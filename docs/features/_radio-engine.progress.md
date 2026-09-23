# Radio optimization engine — progress

Detailed dated log for this blueprint. Brief: [`_radio-engine.md`](_radio-engine.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-08-17: radio insight modules + feature-access guards + morning report compose.
- 2026-08-19: detectors score vs operator targets; TTL cache on expensive scans.

## 2026-08-19

- Done: Network Health scorecard uses operator `threshold_bad` (Retainability 2%, Accessibility 98%, Mobility 95%, Interference −95 dBm, Utilization 80%)
- Done: Radio detectors (capacity, neighbor quality, mobility, IRAT, overshooting HO SR, group health) score against those targets instead of hardcoded 70/95/96/97 cutoffs
- Done: NH APIs no longer 400 on missing KPI (defaults to first precomputed); vendor/rat/top_n hardened; "development stage" label removed
- Done: UI — category scorecard, groups panel, vs-target column, direction-aware delta colors, threshold line on charts, select-page default fix
- Done: TTL cache for expensive radio scans (inventory, neighbors, PM recipes, sleeping detector, sector health, insight builders). `?refresh=1` busts the cache. TTL default 900s (`NCM_RADIO_SECTION_TTL`).
- Done: Sector Health / Excel matrix no longer overlay Sleeping Cells (PM). Coverage is metadata.db only (active vs all configured).
- Done: XML Parser Save/Load Profile endpoints (were 404) + MO/golden-rule validation on upload
- Done: XML Generator pre-flight validation against dictionary, golden rules, and CM snapshot diff
- Done: Parameter Dictionary list index cache (cold ~4 ms) + network values vs default in the parameter detail
- Done: Performance Dictionary index-only list (was 1.76 s); Huawei MAE counter tab; KPI "ref" link from Performance Explorer; data-dependent unit test skips when cache missing
- Done: CM Parameter Audit golden rules: band/area scope, version, approval/baseline; detector honors the same scope
- **NEXT:** Browser-verify `/xml-parser`, `/excel-generator`, `/parameter-dictionary`, `/performance-dictionary`, `/cm-parameter-audit`

## 2026-08-17 (roadmap)

- Done: Nokia LB pipeline verify (rules + RAML XML dry-run + `/api/nokia-load-balancing/verify`). Live OSS import stays confirmation-gated; this host does not auto-push.
- Done: Huawei Load Balancing on Network Balance SQLite (CellMLB propose → Excel/MML). No U2020 push.
- Done: Neighbor 5G-5G + azimuth/freshness; sleeping-cell vs live FM; groups API on Network Health; Change Impact PM across RATs
- Done: Mobility Explorer, Alarm–PM Correlator, Group Health, IRAT/Vendor Border
- Done: KPI aliases for 2G/3G/5G; feature-access guards on radio insight modules; morning report composes the new outputs
- Modified: `app.py`, `core/radio/`, `core/module_access.py`, `core/module_versions.py`, `modules/nokia_load_balancing/`, `modules/huawei_load_balancing/`, new radio modules, `templates/dashboard.html`
