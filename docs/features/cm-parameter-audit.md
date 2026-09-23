# CM Parameter Audit

Golden-rule audit of live/snapshot CM vs expected values.

| | |
|---|---|
| Route | `/cm-parameter-audit` |
| Module | `modules/cm_parameter_audit/` (`cache.py`, `export.py`) |
| Detector | `core.radio.insights.cm_parameter_audit` + `core/radio/cm_store.py` |
| Access | all |
| Version | from `modules/cm_parameter_audit/version.py` |

## Purpose

Rules with band/area scope, version, approval/baseline. Detector honors the same scope.

## Approach

Rules persist in the CM snapshot DB (`cm_store`). Approve/baseline is part of the product — do not silently change a rule’s expected value without going through upsert/approve.

## Progress

Dated work log: [`cm-parameter-audit.progress.md`](cm-parameter-audit.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

**Parked:** browser-verify `/cm-parameter-audit`.

## Watch-outs

Live query path also exists in `core/radio/cm_live.py` — know whether you are auditing a **snapshot** or **live OSS**.
