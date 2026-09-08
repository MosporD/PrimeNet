# NE Comparison

Diff two network elements’ configuration.

| | |
|---|---|
| Route | `/ne-comparison` |
| Module | `modules/ne_comparison/routes.py` |
| Access | all |
| Version | V1.0 |

## Purpose

Side-by-side / delta of MO parameters between two NEs.

## Approach

Diff engine is in this module (large `routes.py`). Do not pull live OSS inside a compare unless the UI already does — prefer extracted files/snapshots.

## History

No dated rewrite in `progress.md`.

## Plans

None parked.

## Watch-outs

Not CM Extractor. Inputs are already-extracted configs.
