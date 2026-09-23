# _Platform — progress

Detailed dated log for this blueprint. Brief: [`_platform.md`](_platform.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## 2026-09-20 (Shared SSO + portal allow-list)

- Done: Central identity on PrimeNet users DB; shared `nexus_session`; Admin portal checkboxes; tower gated by allow-list.

## 2026-09-16 (Suite launcher + shared activation for testing)

- Done: `python app.py` starts NexusCore (8000) + PrimeNet (8001) + NexPulse (8002).
- Done: Shared activation gate for testing — unlock once at PrimeNet `/activation`; NexusCore/NexPulse redirect there until unlocked. Per-platform activation later (`NCM_SHARED_ACTIVATION=0`).

## 2026-09-16 (Separate platform processes)

- Done: Three entry apps — `nexuscore_app.py` (lobby), `primenet_app.py` (engineering), `nexpulse_app.py` (marketing).
- Done: Per-platform users DB + cookies (`nxc_session`, `primenet_session`, `nexpulse_session`); no SSO handoff.
- Done: `core/platform/` base factory + parameterized identity; marketing `access.py` no longer imports `database_enhanced`.
- Done: Docker Compose services `nexuscore` / `primenet` / `nexpulse`; `app.py` shim → PrimeNet.
- Tests: `core/platform/test_platform.py`; marketing architecture test updated.

## 2026-09-02 (feature briefs)

- Done: Agent context briefs for every dashboard tile + shared platform (`docs/features/`). Not user manuals. Cursor rule `feature-briefs.mdc` loads them when those files are in play. Update History/Plans on the matching brief when a feature actually changes.

## 2026-08-03

- Done: Nokia Load Balancing (`modules/nokia_load_balancing/`, `/nokia-load-balancing`) — admin AMLE workflow. Legacy `/amle-optimizer` redirects here (not a separate module)
- Done: Huawei Load Balancing stub (`modules/huawei_load_balancing/`)
- Done: Network Balance share auto-load (`\\RNO-WAN\Network Balance`) + daily Nokia/Huawei CSV ingest → SQLite
- Done: File discovery from Mover.py logic (vendor/date from filename)
- Done: Live CM extract (`NOKLTE:AMLEPR`) via existing CM Extractor client
- Done: Proposed RAML XML + Excel export; rules in `modules/nokia_load_balancing/config.py`
- Modified: `app.py`, `core/module_access.py`, `core/module_versions.py`, `templates/dashboard.html`, `sync_config.py`, `db/runtime.py`, `modules/sync/scheduler.py`, `.env.example`

## 2026-08-02

- Done: Scheduler RAM isolation — stream pipeline output, isolate network-health precalc
- Modified: `core/load_monitor.py`, `core/subprocess_runner.py`, `modules/sync/scheduler.py`

## 2026-07-28

- Done: XML uploads allow DOCTYPE via defusedxml
- Done: CM Extractor site lists driven from PrimeNet metadata

## 2026-07-23

- Done: PrimeNet `report_date` / `report_time` columns for PM charts
- Done: Neighbor sync on its own cadence with full SQLite replace

## 2026-07-22

- Done: Power BI link-out gallery (`modules/power_bi/`) — catalog-driven list, opens reports in Power BI Service
- Done: Dashboard card + nav for Power BI Reports (`/power-bi`); dark-mode tokens; theme checklist in `docs/FRONTEND_THEME.md`
- Done: Admin-configurable feature access; Developer Documentation module; onboarding course (`docs/course`)
- Done: Per-user vendor credentials; adaptive RAM limits for ingest / heavy PM queries
- **Backlog:** Power BI embed-token flow when workspace gets Premium/Fabric; verify gallery light + dark

## YYYY-MM-DD

- Done: <what was verified>
- **NEXT**: <single immediate task>
```
