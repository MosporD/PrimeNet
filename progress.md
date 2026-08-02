# PrimeNet — progress log

Dated log of verified work. Mark items done only after end-to-end verification.

## 2026-08-02

- Done: `pm_warehouse/` pilot — raw NBI counter ingestion + aggregation in
  PostgreSQL (Nokia TS 32.435 adapter, per-family fact tables, h/d/w/m rollups,
  query-time KPI formula compiler). Verified end-to-end in sandbox Postgres 16:
  idempotent double-ingest, hand-computed DRB SSR from raw XML == warehouse
  value exact to 6 decimals, eNB/network object aggregation, 47k rows/s merge.
  Measured results in `pm_warehouse/README.md`.
- **NEXT**: obtain a real Huawei U2020 PM NBI sample + `data/huawei_pm_counters/`
  CSVs; then a multi-eNB real-file day from NetAct for the phase-4 OSS diff.

## 2026-07-22

- Done: Power BI link-out gallery module (`modules/power_bi/`) — catalog-driven report list, opens reports in Power BI Service
- Done: Dashboard card + nav entry for Power BI Reports (`/power-bi`)
- Done: Dark mode tokens for Power BI gallery (`power_bi.css`, `body.pbi-page`)
- Done: Theme guide updated — mandatory dark-mode checklist in `docs/FRONTEND_THEME.md`
- Modified: `app.py`, `core/module_access.py`, `core/module_versions.py`, `templates/dashboard.html`
- **NEXT**: When workspace gets Premium/Fabric capacity, add embed-token flow; verify gallery in browser (light + dark)

## 2026-07-06

- In progress: dashboard / module UI unification (constellation theme, shared CSS)
- Modified: `templates/dashboard.html`, `login.html`, `register.html`, `radio_module.html`
- Modified: `static/css/dashboard.css`, `constellation.css`, `radio_modules.css`, `static/js/common.js`, `constellation.js`
- Modified: module templates under `modules/*/templates/` (admin, network health, performance, etc.)
- **NEXT**: verify constellation background + module pages in browser; confirm mobile layout on `radio_module.html`

## Template

```
## YYYY-MM-DD
- Done: <what was verified>
- **NEXT**: <single immediate task>
```
