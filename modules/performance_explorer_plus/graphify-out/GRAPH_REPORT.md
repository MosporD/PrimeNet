# Graph Report - modules\performance_explorer_plus  (2026-09-11)

## Corpus Check
- 3 files · ~2,683 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 43 nodes · 86 edges · 8 communities (7 shown, 1 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3fa123c8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- login_required
- performance_explorer_plus.js
- runQuery
- routes.py
- queryPayload
- get_current_user
- _guard_access

## God Nodes (most connected - your core abstractions)
1. `login_required()` - 14 edges
2. `runQuery()` - 7 edges
3. `get_current_user()` - 5 edges
4. `page()` - 5 edges
5. `queryPayload()` - 5 edges
6. `api_kpis_save()` - 4 edges
7. `api_views_save()` - 4 edges
8. `api_rollup()` - 4 edges
9. `setMode()` - 4 edges
10. `showExploreResult()` - 4 edges

## Surprising Connections (you probably didn't know these)
- `api_counters()` --references--> `login_required()`  [EXTRACTED]
  modules/performance_explorer_plus/routes.py → modules/performance_explorer_plus/routes.py  _Bridges community 0 → community 3_
- `api_kpis_save()` --references--> `login_required()`  [EXTRACTED]
  modules/performance_explorer_plus/routes.py → modules/performance_explorer_plus/routes.py  _Bridges community 0 → community 5_
- `page()` --calls--> `get_current_user()`  [EXTRACTED]
  modules/performance_explorer_plus/routes.py → modules/performance_explorer_plus/routes.py  _Bridges community 5 → community 3_
- `runQuery()` --calls--> `queryPayload()`  [EXTRACTED]
  modules/performance_explorer_plus/static/performance_explorer_plus.js → modules/performance_explorer_plus/static/performance_explorer_plus.js  _Bridges community 4 → community 2_

## Import Cycles
- None detected.

## Communities (8 total, 1 thin omitted)

### Community 0 - "login_required"
Cohesion: 0.39
Nodes (9): route, api_health(), api_kpis_delete(), api_kpis_list(), api_kpis_validate(), api_objects(), api_query(), api_views_list() (+1 more)

### Community 1 - "performance_explorer_plus.js"
Cohesion: 0.32
Nodes (4): loadCounters(), loadObjects(), renderCounterList(), renderObjects()

### Community 2 - "runQuery"
Cohesion: 0.32
Nodes (8): refreshHealth(), renderChart(), renderMeta(), renderTable(), runQuery(), setMode(), setViewMode(), showExploreResult()

### Community 3 - "routes.py"
Cohesion: 0.40
Nodes (5): api_counters(), api_export(), format_user(), page(), Performance Explorer Plus — Nokia raw-counter warehouse UI.

### Community 4 - "queryPayload"
Cohesion: 0.40
Nodes (5): exportCsv(), metricMode(), queryPayload(), saveView(), syncMetricModeUi()

### Community 5 - "get_current_user"
Cohesion: 0.50
Nodes (4): api_kpis_save(), api_rollup(), api_views_save(), get_current_user()

## Knowledge Gaps
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `login_required()` connect `login_required` to `routes.py`, `get_current_user`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `_guard_access()` connect `_guard_access` to `routes.py`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Why does `runQuery()` connect `runQuery` to `performance_explorer_plus.js`, `queryPayload`?**
  _High betweenness centrality (0.008) - this node is a cross-community bridge._