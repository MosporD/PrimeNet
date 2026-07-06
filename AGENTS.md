# PrimeNet

Flask telecom platform for radio network performance and configuration management.
Entry point: `app.py`. Vendors: Nokia, Huawei. RATs: 2G–5G.

## Architecture

- **App shell**: `app.py` registers blueprints, loads `.env`, runs activation gate.
- **Feature modules**: `modules/<name>/` — each has `routes.py`, `templates/`, optional `static/`, `logic.py`.
- **Shared infra**: `routes/auth_routes.py` (login/session), `routes/activation_routes.py`, `core/`, `utils/`, `db/`.
- **Radio API modules**: thin wrappers (`modules/radio_api`, `neighbor_quality`, etc.) delegate to `core/radio/`.
- **ETL pipeline**: canonical code in `pipeline/`; legacy pull/load scripts in `scripts/pipeline/`.
- **UI shell**: `templates/dashboard.html` (constellation deck), `templates/radio_module.html` (shared radio filter layout).
- **Global styles**: `static/css/common.css`, `dashboard.css`, `constellation.css`, `radio_modules.css`.

## Conventions

- Register every new blueprint in `app.py` (import + `app.register_blueprint`).
- Module blueprints use `template_folder="templates"` and module-local `static_folder` when needed.
- Auth: copy `login_required` decorator pattern from existing modules; session via `session_token` cookie.
- PM data: SQLite via `db/runtime.py` and `sync_config.py` path constants.
- Module access control: `core/module_access.py`.

## Do not edit

- `modules/parameter_dictionary/huawei_params/` — scraped Huawei reference HTML (~19k files), served at runtime only.
- `raw/`, `*.db`, `sync_downloads/` — runtime/generated data, not source.

## Watch-outs

- KPI query strings are stripped from access logs in `app.py` (`ConciseRequestHandler`).
- Pipeline path taxonomy lives in `pipeline/paths.py`; prefer `pipeline/orchestrators/` over ad-hoc scripts.
- Huawei daily exports stage in `raw/huawei/{cells,groups}/all/daily` before RAT split.
- Dashboard constellation background: `static/js/constellation.js` + `static/css/constellation.css`.
- Large HTML templates (e.g. `dashboard.html`) — edit targeted sections, avoid full-file rewrites.

## Session handoff

Read `progress.md` for current work and the NEXT pointer. Scope is defined in `checklist.md`.
