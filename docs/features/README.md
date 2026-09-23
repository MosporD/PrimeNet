# Feature briefs (agent context)

These files are **implementation context**, not user manuals. Read the matching
brief **and** its `.progress.md` **before** changing a feature.

| File | Role |
|---|---|
| [`docs/feature.md`](../feature.md) | Full map — user view + plan pointers |
| `docs/features/<slug>.md` | Purpose, approach, plans, watch-outs |
| `docs/features/<slug>.progress.md` | Dated log, Current track, module NEXT |
| [`progress.md`](../../progress.md) | Root **daily journal** — topic bullets only |

Do **not** treat `docs/MODULE_AUDIT.md` (2026-08-19) as current — several gaps
listed there were fixed later (XML parser profiles, dictionary caches, Network
Health thresholds on detectors, Huawei load balancing, neighbor Excel export).

## How to use

1. Skim [`docs/feature.md`](../feature.md) for the blueprint you are touching.
2. `python -m graphify query "<feature>"` for the code graph.
3. Open `docs/features/<slug>.md` (slug = dashboard `data-module-id` / href id;
   portals use product slugs such as `nexpulse`).
4. Open `docs/features/<slug>.progress.md` for history and this module’s NEXT.
5. Radio-optimization wrappers: also read [`_radio-engine.md`](_radio-engine.md).
6. After the change:
   - Append `## YYYY-MM-DD` to `<slug>.progress.md` (details live here).
   - Update **Plans** on the brief if the roadmap moved.
   - Add **one short topic bullet** to root [`progress.md`](../../progress.md).
   - Bump `core/module_versions.py` when the UI label should change.

Cross-cutting platform work (suite launcher, shared activation, etc.) goes in
[`_platform.progress.md`](_platform.progress.md).

## Adding a feature

1. Blueprint in `modules/<name>/` + `app.register_blueprint` in `primenet_app.py`
   (portals: `portals/<name>/` + factory — not a PrimeNet tile).
2. `NAV_SECTIONS` + dashboard `data-module-id` + `core/module_versions.py` (PrimeNet).
3. New brief `docs/features/<slug>.md` (Purpose, Approach, Progress link, Plans,
   Watch-outs) and empty `docs/features/<slug>.progress.md`. Do not invent roadmap.
4. Radio issue-list tiles: use `make_radio_module` and a short brief that points
   at [`_radio-engine.md`](_radio-engine.md).

## Shared platform (not dashboard tiles)

| Brief | Code |
|---|---|
| [`_radio-engine.md`](_radio-engine.md) | `core/radio/`, `templates/radio_module.html` |
| [`auth-activation.md`](auth-activation.md) | `routes/auth_routes.py`, `routes/activation_routes.py` |
| [`postgres-runtime.md`](postgres-runtime.md) | `db/runtime.py`, `db/pg_domains.py` |
| [`sync.md`](sync.md) | `modules/sync/`, `pipeline/` |
| [`_platform.progress.md`](_platform.progress.md) | Cross-cutting platform / suite work |

## NexusCore portals (outside `modules/`)

| Brief | Progress | Code |
|---|---|---|
| [`nexpulse.md`](nexpulse.md) | [`nexpulse.progress.md`](nexpulse.progress.md) | `portals/marketing/` (NexPulse) |

## Index

### Overview & Performance

- [Dashboard](dashboard.md) · [progress](dashboard.progress.md)
- [Performance Explorer](performance.md) · [progress](performance.progress.md)
- [Performance Explorer Plus](performance-explorer-plus.md) · [progress](performance-explorer-plus.progress.md)
- [Huawei PM Query Studio](performance-analytics.md) · [progress](performance-analytics.progress.md)
- [Network Coverage Heatmap](cell-heatmap.md) · [progress](cell-heatmap.progress.md)
- [Network Map](network-map.md) · [progress](network-map.progress.md)
- [Neighbor Analysis](neighbor-analysis.md) · [progress](neighbor-analysis.progress.md)
- [Performance Reports](reports.md) · [progress](reports.progress.md)
- [Power BI Reports](power-bi.md) · [progress](power-bi.progress.md)
- [Sector Health](sector-health.md) · [progress](sector-health.progress.md)
- [Conflict Map](conflict-map.md) · [progress](conflict-map.progress.md)
- [Adjacency GIS](adjacency-gis.md) · [progress](adjacency-gis.progress.md)
- [Femto PM](femto-pm.md) · [progress](femto-pm.progress.md)
- [Fault Management](fault-management.md) · [progress](fault-management.progress.md)

### Radio Optimization

- [SON Optimization Insights](son-analytics.md) · [progress](son-analytics.progress.md)
- [Optimization Cases](optimization-cases.md) · [progress](optimization-cases.progress.md)
- [Network Health Overview](network-health.md) · [progress](network-health.progress.md)
- [RF Optimization Workbench](rf-optimization.md) · [progress](rf-optimization.progress.md)
- [Neighbor Quality Analyzer](neighbor-quality.md) · [progress](neighbor-quality.progress.md)
- [Capacity Hotspots](capacity-hotspots.md) · [progress](capacity-hotspots.progress.md)
- [Sleeping Cell Detector](sleeping-cells.md) · [progress](sleeping-cells.progress.md)
- [Layer Coverage Gaps](layer-coverage.md) · [progress](layer-coverage.progress.md)
- [Overshooting Detector](overshooting-detector.md) · [progress](overshooting-detector.progress.md)
- [Change Impact Tracker](change-impact.md) · [progress](change-impact.progress.md)
- [Radio Morning Report](radio-morning-report.md) · [progress](radio-morning-report.progress.md)
- [Nokia Load Balancing](nokia-load-balancing.md) · [progress](nokia-load-balancing.progress.md)
- [Huawei Load Balancing](huawei-load-balancing.md) · [progress](huawei-load-balancing.progress.md)
- [Mobility / HO Explorer](mobility-explorer.md) · [progress](mobility-explorer.progress.md)
- [Alarm–PM Correlator](alarm-impact.md) · [progress](alarm-impact.progress.md)
- [Group / Cluster Health](group-health.md) · [progress](group-health.progress.md)
- [IRAT / Vendor Border](irat-border.md) · [progress](irat-border.progress.md)

### Configuration

- [Configuration Dashboard](configuration-dashboard.md) · [progress](configuration-dashboard.progress.md)
- [Parameter Dictionary](parameter-dictionary.md) · [progress](parameter-dictionary.progress.md)
- [Performance Dictionary](performance-dictionary.md) · [progress](performance-dictionary.progress.md)
- [Configuration Data Extractor](cm-extractor.md) · [progress](cm-extractor.progress.md)
- [CM Parameter Audit](cm-parameter-audit.md) · [progress](cm-parameter-audit.progress.md)
- [XML Parser](xml-parser.md) · [progress](xml-parser.progress.md)
- [XML Generator](excel-generator.md) · [progress](excel-generator.progress.md)
- [NE Comparison](ne-comparison.md) · [progress](ne-comparison.progress.md)
- [RET Management](ret-management.md) · [progress](ret-management.progress.md)
- [Radio Hardware Inventory Report](rru-inventory.md) · [progress](rru-inventory.progress.md) (Hardware tab of Configuration Dashboard)
- [Config Task Scheduler](config-task-scheduler.md) · [progress](config-task-scheduler.progress.md)
- [Config History](config-history.md) · [progress](config-history.progress.md)
- [Network Management](network-management.md) · [progress](network-management.progress.md)
- [RAN Feature Library](ran-features.md) · [progress](ran-features.progress.md)
- [Drive Test Viewer](drive-test-viewer.md) · [progress](drive-test-viewer.progress.md)

### Administration & helpers

- [Admin Panel](admin-panel.md) · [progress](admin-panel.progress.md)
- [Developer Documentation](documentation.md) · [progress](documentation.progress.md)
- [User Profile](user-profile.md) · [progress](user-profile.progress.md)
- [Elevation](elevation.md) · [progress](elevation.progress.md)
- [Radio API](radio-api.md) · [progress](radio-api.progress.md)
- [Auth / activation](auth-activation.md) · [progress](auth-activation.progress.md)
- [Sync / ETL](sync.md) · [progress](sync.progress.md)
- [Postgres runtime](postgres-runtime.md) · [progress](postgres-runtime.progress.md)
