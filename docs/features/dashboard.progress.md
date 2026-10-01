# Dashboard — progress

Detailed dated log for this blueprint. Brief: [`dashboard.md`](dashboard.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Parked:** Dark-mode contrast browser verify.

**NEXT:** Browser verify Operations Panel health on server after deploy (PG size + latest timestamps).

---
## 2026-10-01 (Operations Panel Postgres health)

- Root cause: `pm_health` / `neighbor_health` still treated leftover `*.db` file size/mtime as live store and used SQLite `rowid` sampling for “latest data”.
- Done: shared `db.runtime.store_health` (schema + `pg_total_relation_size`); timestamp bounds via MIN/MAX / `ctid` sample; unmapped domains report MISSING under Postgres-only runtime.
- NEXT: Smoke Operations Panel Database Health + Neighbor Health on 97.141 after rebuild.

## 2026-09-29 (Postgres-only)

- How it works on PG: catalogued stores open via `open_db` / `open_store` into Postgres schemas (`NCM_DATABASE_URL` required). No SQLite file fallback for this module's data plane.
- NEXT: Smoke primary routes after Daily load on server PG.

## From brief History (migrated 2026-09-17)

- 2026-09-06: UI unification pass — auth pages on shared `login.css`; module body classes / logout / dark allowlist; dashboard inline style removed.
- 2026-09-02: dashboard tiles render `MODULE_VERSIONS` chips in HTML (not JS-only), including CM Parameter Audit **V4.7**.
- Dashboard constellation, feature-access, load-balancing tiles, radio insight tiles (2026-08).

## 2026-09-08 (dark-mode UI fixes)

- Done: Cell Heatmap status text, Femto Create KPI button, SON header (no READ-ONLY, standard topbar), CM Extractor scrollbars, Parameter Audit golden-rules panel, XML Parser plan validation, Overshooting/radio-module opaque dark background.
- Deploy note: server must `git pull` to `a575aeba+` then rebuild; these fixes are local until pushed.

## 2026-09-06 (UI unification)

- Done: Extracted login inline CSS → `static/css/login.css`; register + activation rebuilt on the same NexusCore constellation shell.
- Done: Module body page-classes for 11 templates; Documentation + SON logout; `common.js` theme toggle mounts on `.doc-header-right`; dark page-class allowlist expanded in `common.css`.
- Done: Dashboard legacy op-sites hide rule moved from inline `<style>` to `dashboard.css`.
- Not done: live browser pass (checklist last box).

## 2026-07-30

- Done: UI zoom pointer sync, Performance Explorer loading UX + site select-all

## 2026-07-06

- In progress: dashboard / module UI unification (constellation theme, shared CSS) — `checklist.md` still open
- Modified: `templates/dashboard.html`, `login.html`, `register.html`, `radio_module.html`
- Modified: `static/css/dashboard.css`, `constellation.css`, `radio_modules.css`, `static/js/common.js`, `constellation.js`
- Modified: module templates under `modules/*/templates/` (admin, network health, performance, etc.)
- **Backlog:** verify constellation background + module pages in browser; confirm mobile layout on `radio_module.html`
