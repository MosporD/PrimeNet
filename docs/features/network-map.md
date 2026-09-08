# Network Map

Leaflet topology: sites, sectors, cells, repeaters.

| | |
|---|---|
| Route | `/network-map` |
| Module | `modules/network_map/routes.py`, `static/map.js`, `templates/network_map.html` |
| Helpers | `repeater_loader.py`, `huawei_prs_tabular.py` |
| Access | all |
| Version | V1.0 |

## Purpose

Geographic network picture from `metadata.db` (sites/cells) plus optional PM overlays and repeaters.

## Approach

- Neighbor **lines** belong to Neighbor Analysis (`/neighbor-analysis`), same blueprint — do not mix the two UIs.
- Metadata queries: `connect_metadata()`. Heavy polygon/site queries already exist — extend, don’t clone.
- Cache-bust `map.js` / `network_map.css` only when those files change.

## History

Map is a long-lived heavy module (Lesson 08). Neighbor Excel (2026-08-31) is on the analysis page, not this one.

## Plans

None parked for the map itself.

## Watch-outs

`routes.py` is huge. Grep the route. Do not full-file rewrite templates.
