# PrimeNet — progress log

Dated log of verified work. Mark items done only after end-to-end verification.

## 2026-08-03

- Done: AMLE Optimizer module (`modules/amle_optimizer/`) — admin-only Nokia AMLE workflow
- Done: Network Balance share auto-load (`\\RNO-WAN\Network Balance`) for sector throughput
- Done: Daily Nokia + Huawei balance CSV ingest → SQLite (`databases/network_balance/all/all/daily/network_balance.db`)
- Done: File discovery from Mover.py logic (vendor/date from filename)
- Done: Live CM extract (`NOKLTE:AMLEPR`) via existing CM Extractor client
- Done: Proposed RAML XML + Excel export; rules in `config.py`
- Modified: `app.py`, `core/module_access.py`, `core/module_versions.py`, `templates/dashboard.html`, `sync_config.py`, `db/runtime.py`, `modules/sync/scheduler.py`, `.env.example`
- **NEXT**: Browser verify `/amle-optimizer` (sector pick → analyze → XML download) with NetAct CM credentials

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
