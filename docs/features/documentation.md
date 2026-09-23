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

## Progress

Dated work log: [`documentation.progress.md`](documentation.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

Course Lesson 07 still calls Huawei LB a stub — briefs here are the correction. Optional later course patch; not required for agents.

## Watch-outs

Feature briefs (`docs/features/`) are **agent** context. This page is the **human** course. Both can exist.
