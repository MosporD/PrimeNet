# Feature briefs (agent context)

These files are **implementation context**, not user manuals. Read the matching
brief **before** changing a feature. Dated session work still lives in
`progress.md`; this folder is the per-blueprint memory.

Do **not** treat `docs/MODULE_AUDIT.md` (2026-08-19) as current — several gaps
listed there were fixed later (XML parser profiles, dictionary caches, Network
Health thresholds on detectors, Huawei load balancing, neighbor Excel export).

## How to use

1. `python -m graphify query "<feature>"` for the code graph.
2. Open `docs/features/<slug>.md` (slug = dashboard `data-module-id` / href id).
3. Radio-optimization wrappers: also read [`_radio-engine.md`](_radio-engine.md).
4. After the change: update **History** (one dated line) and **Plans** if the
next step moved. Bump `core/module_versions.py` when the UI label should change.

## Adding a feature

1. Blueprint in `modules/<name>/` + `app.register_blueprint` in `app.py`.
2. `NAV_SECTIONS` + dashboard `data-module-id` + `core/module_versions.py`.
3. New brief `docs/features/<slug>.md` using the same headings as the others
   (Purpose, Approach, History, Plans, Watch-outs). Do not invent roadmap.
4. Radio issue-list tiles: use `make_radio_module` and a short brief that points
   at [`_radio-engine.md`](_radio-engine.md).

## Shared platform (not dashboard tiles)

| Brief | Code |
|---|---|
| [`_radio-engine.md`](_radio-engine.md) | `core/radio/`, `templates/radio_module.html` |
| [`auth-activation.md`](auth-activation.md) | `routes/auth_routes.py`, `routes/activation_routes.py` |
| [`postgres-runtime.md`](postgres-runtime.md) | `db/runtime.py`, `db/pg_domains.py` |
| [`sync.md`](sync.md) | `modules/sync/`, `pipeline/` |

## Index

### Overview & Performance

- [Dashboard](dashboard.md)
- [Performance Explorer](performance.md)
- [Huawei PM Query Studio](performance-analytics.md)
- [Network Coverage Heatmap](cell-heatmap.md)
- [Network Map](network-map.md)
- [Neighbor Analysis](neighbor-analysis.md)
- [Performance Reports](reports.md)
- [Power BI Reports](power-bi.md)
- [Sector Health](sector-health.md)
- [Conflict Map](conflict-map.md)
- [Femto PM](femto-pm.md)
- [Fault Management](fault-management.md)

### Radio Optimization

- [SON Optimization Insights](son-analytics.md)
- [Network Health Overview](network-health.md)
- [RF Optimization Workbench](rf-optimization.md)
- [Neighbor Quality Analyzer](neighbor-quality.md)
- [Capacity Hotspots](capacity-hotspots.md)
- [Sleeping Cell Detector](sleeping-cells.md)
- [Layer Coverage Gaps](layer-coverage.md)
- [Overshooting Detector](overshooting-detector.md)
- [Change Impact Tracker](change-impact.md)
- [Radio Morning Report](radio-morning-report.md)
- [Nokia Load Balancing](nokia-load-balancing.md)
- [Huawei Load Balancing](huawei-load-balancing.md)
- [Mobility / HO Explorer](mobility-explorer.md)
- [Alarm–PM Correlator](alarm-impact.md)
- [Group / Cluster Health](group-health.md)
- [IRAT / Vendor Border](irat-border.md)

### Configuration

- [Parameter Dictionary](parameter-dictionary.md)
- [Performance Dictionary](performance-dictionary.md)
- [Configuration Data Extractor](cm-extractor.md)
- [CM Parameter Audit](cm-parameter-audit.md)
- [XML Parser](xml-parser.md)
- [XML Generator](excel-generator.md)
- [NE Comparison](ne-comparison.md)
- [RET Management](ret-management.md)
- [Config Task Scheduler](config-task-scheduler.md)
- [Config History](config-history.md)
- [Network Management](network-management.md)
- [RAN Feature Library](ran-features.md)
- [Drive Test Viewer](drive-test-viewer.md)

### Administration & helpers

- [Admin Panel](admin-panel.md)
- [Developer Documentation](documentation.md)
- [User Profile](user-profile.md)
- [Elevation](elevation.md)
- [Radio API](radio-api.md)
