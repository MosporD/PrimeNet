# Neighbor Quality Analyzer

Issue list for bad/missing neighbor relations. **Not** the Neighbor Analysis map.

| | |
|---|---|
| Route | `/neighbor-quality` |
| API | `/api/neighbor-quality/issues` |
| Package | `modules/neighbor_quality/` |
| Detector | `core.radio.insights.neighbor_quality` → `core/radio/neighbor.py` |
| Access | admin |
| Version | V1.0 |
| Shell | `templates/radio_module.html` |

See [`_radio-engine.md`](_radio-engine.md).

## Purpose

Score neighbor relations (HO, distance, azimuth, freshness) against operator targets.

## Approach

Change `core/radio/neighbor.py`. Line cap `NEIGHBOR_MAX_LINES` also feeds SON Topology — raising it requires an ML rebuild to show up there.

## History

- 2026-08-17: 5G-5G + azimuth/freshness. 2026-08-19: vs-target scoring.

## Plans

Do not merge with `/neighbor-analysis`.

## Watch-outs

Map/Excel tool is Neighbor Analysis. This is the ranked issue API.
