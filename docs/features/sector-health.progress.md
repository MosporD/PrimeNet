# Sector Health — progress

Detailed dated log for this blueprint. Brief: [`sector-health.md`](sector-health.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-09-08: Stopped excluding Nokia `2G / GSM 900` (and sparse DCS labels) from the coverage matrix — that zeroed Nokia 2G sector counts. Normalize to `2G / GSM900`. Version V1.3.
- 2026-08-19: Sleeping Cells overlay removed from Sector Health / Excel matrix. Version V1.2.

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
