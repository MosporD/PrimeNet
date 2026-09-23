# Nokia Load Balancing — progress

Detailed dated log for this blueprint. Brief: [`nokia-load-balancing.md`](nokia-load-balancing.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-08-03: module + ingest. 2026-08-11: ingest process monitor.
- 2026-08-17: pipeline verify (rules + RAML dry-run). No auto-push on this host.

## 2026-08-17 (roadmap)

- Done: Nokia LB pipeline verify (rules + RAML XML dry-run + `/api/nokia-load-balancing/verify`). Live OSS import stays confirmation-gated; this host does not auto-push.
- Done: Huawei Load Balancing on Network Balance SQLite (CellMLB propose → Excel/MML). No U2020 push.
- Done: Neighbor 5G-5G + azimuth/freshness; sleeping-cell vs live FM; groups API on Network Health; Change Impact PM across RATs
- Done: Mobility Explorer, Alarm–PM Correlator, Group Health, IRAT/Vendor Border
- Done: KPI aliases for 2G/3G/5G; feature-access guards on radio insight modules; morning report composes the new outputs
- Modified: `app.py`, `core/radio/`, `core/module_access.py`, `core/module_versions.py`, `modules/nokia_load_balancing/`, `modules/huawei_load_balancing/`, new radio modules, `templates/dashboard.html`

## 2026-08-17

- Done: Refreshed this log from git — previous NEXT items (AMLE verify, Power BI embed, constellation checks) were stale vs `main`
- Done: Integrated graphify — AST code map at `graphify-out/` (7110 nodes, 18838 edges, 245 communities, 0 LLM tokens). CLI: `python -m graphify` (exe often not on PATH)
- Done: Graphify maps embedded on `/documentation` (Overview → Code map / Call flow); Lesson 12 removed
- Done: Documentation page fills `--ui-vh` (was `100vh` under 0.67 zoom)
- Done: Course/ARCHITECTURE catch-up — load balancing, Power BI, feature access, vendor creds, Docker
- Modified: `progress.md`, `AGENTS.md`, `docs/course/`, `docs/ARCHITECTURE.md`, `modules/documentation/`
- **NEXT:** Browser-verify `/nokia-load-balancing` with NetAct CM credentials

## 2026-08-11

- Done: Network Balance ingest process monitor in Nokia Load Balancing UI
- Done: Performance Explorer site-search fix
- Done: Docker apt-get fix for networks that block HTTP
- Modified: `Dockerfile`, `modules/nokia_load_balancing/`, `modules/performance/`

## 2026-08-05

- Done: SMB auto-mount for Network Balance on Linux Docker
- Done: Performance chart layouts, search deep links, RET writes, admin activity
- Done: Huawei HedEx in-page TOC links
- Done: Nokia NE list site-ID resolution cache
- Modified: `deploy/`, `docker-compose.yml`, `core/cm_extractor/nokia_discovery.py`, `modules/performance/`, `modules/ret_management/`, `modules/ran_features/hdx.py`
