# Radio optimization engine

Shared by every `/radio-*` style tile that renders `radio_module.html`.
Not a dashboard card. Read this **and** the per-module brief.

| | |
|---|---|
| Factory | `core/radio/blueprint.py` `make_radio_module()` |
| Shell | `templates/radio_module.html` + `static/css/radio_modules.css` + `static/js/radio_modules.js` |
| Auth | `core/radio/web.py` (`admin_required`, `attach_feature_guard`) |
| Scoring | `core/radio/scoring.py` — `score_vs_preset` / `issue` / `filter_rows` |
| Cache | `core/radio/section_runner.py` — TTL default 900s (`NCM_RADIO_SECTION_TTL`); `?refresh=1` busts |

## Shape

Thin `modules/<name>/` (often `__init__.py` + 30–40 line `routes.py`) calls a detector in `core/radio/insights.py` (or a sibling: `neighbor.py`, `mobility.py`, `groups.py`, `alarm_impact.py`). Page + `/api/.../issues` returning `{success, issues, summary}`.

Sleeping Cells is the exception with real logic in `modules/sleeping_cells/logic.py`.

## Approach

- Change detection/scoring in `core/radio/`, not by forking the HTML.
- Thresholds come from Network Health operator presets (`modules/network_health/config.py` `threshold_bad`) via `score_vs_preset`. Do not re-hardcode 70/95/96/97.
- Pass `area` into a builder only if its signature has `area` (group/controller PM often does not).
- Do not overlay Sleeping Cells (PM) onto Sector Health coverage (metadata).
- Neighbor line scans honor `NEIGHBOR_MAX_LINES` (raised for SON Topology).

## History

- 2026-08-17: radio insight modules + feature-access guards + morning report compose.
- 2026-08-19: detectors score vs operator targets; TTL cache on expensive scans.

## Plans

No closed-loop SON. No OSS write from these issue lists.

## Watch-outs

`docs/course/07-module-reference.md` still calls Huawei Load Balancing a stub — that is stale (V1.2 CellMLB exists).
