# Dashboard

Constellation home. Not its own blueprint — served from `app.py` / auth after login.

| | |
|---|---|
| Page | `/dashboard` — `templates/dashboard.html` |
| CSS/JS | `static/css/dashboard.css`, `constellation.css`, `static/js/constellation.js`, `dashboard.js` |
| Catalog | `core/module_access.py` `NAV_SECTIONS` + `core/module_versions.py` |
| Access | all authenticated |

## Purpose

Tile deck for every tool. Cards use `data-module-id` (that id **is** the feature-brief slug). Version labels come from `MODULE_VERSIONS`.

## Approach

- Edit **targeted sections** of `dashboard.html`. Do not rewrite the whole file.
- New tools: register blueprint in `app.py`, add `NAV_SECTIONS` + dashboard card + `module_versions.py` + `docs/features/<slug>.md`.
- Theme tokens: constellation CSS is the source of truth (`checklist.md` UI unification).
- Visual pulse: `core/network_activity.py` (PM traffic). Cosmetic only.

## Progress

Dated work log: [`dashboard.progress.md`](dashboard.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

UI unification in `checklist.md` mostly checked (2026-09-06). Remaining: browser verify light/dark on dashboard + one radio + one standalone + login.

## Watch-outs

`data-module-id` must match `HREF_MODULE_IDS` / this folder’s filename.
