# Performance Explorer

Main KPI explorer. Biggest module.

| | |
|---|---|
| Route | `/performance` |
| Module | `modules/performance/` (`routes.py`, `kpi_catalog.py`, `kpi_mapping.py`) |
| Access | all |
| Version | V1.0 |
| DBs | vendor PM hourly/daily + groups via `open_db` / `_open_pm_db` |

## Purpose

Cell/site/group KPI trends and tables, Nokia + Huawei, 2G–5G, hourly/daily, CSV export. Column lists are discovered from live tables, not a fixed schema.

## Approach

- Do not read `routes.py` top to bottom. Grep `@performance_bp.route` for the view you need.
- Routing helpers: `_pm_db_for_vendor`, `_groups_db_for_vendor`, `_open_pm_db`.
- Caches keyed by PM mtime (`_pm_data_version_token`). Invalidate by writing the DB, not by guessing.
- ATTACH joins: `performance_meta_pm_conn` (SQLite attach vs PG schema alias). Metadata + PM must be the same backend.
- New KPIs: catalog/mapping + headers DB, not hardcoded SELECT lists.

## History

- 2026-08-05: chart layouts, site-search fix.
- 2026-08-31: PM opens go through `open_db` for optional Postgres.

## Plans

None specific. KPI “ref” links into Performance Dictionary already exist.

## Watch-outs

Module defines its own `login_required` (pre-shared-helper). Functionally same as `core/radio/web.py`. Huawei 4G cell identity in **SON** `pm_helpers` is a different file — do not “fix” LocalCell Id vs Cell Name here without an explicit ask.
