# Developer Documentation

In-app course + architecture + graphify maps. Admin only.

| | |
|---|---|
| Route | `/documentation` |
| Module | `modules/documentation/` |
| Access | admin |

## Purpose

Serve `docs/course/`, `docs/ARCHITECTURE.md`, and graphify HTML (`graph.html`, call flow) via a **catalog** (`_catalog()` in `routes.py`) — no arbitrary filesystem reads.

## Approach

New human docs: add to the catalog. Graphify maps: run `python -m graphify update .` after code edits. Do not dump `graphify-out/cache/` into explanations.

## History

- 2026-08-17: graphify embedded (Overview → Graph / Code map / Call flow). Lesson 12 removed.

## Plans

Course Lesson 07 still calls Huawei LB a stub — briefs here are the correction. Optional later course patch; not required for agents.

## Watch-outs

Feature briefs (`docs/features/`) are **agent** context. This page is the **human** course. Both can exist.
