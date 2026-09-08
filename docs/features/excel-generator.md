# XML Generator

Build config XML/Excel from templates (dashboard label: Configuration XML Generator).

| | |
|---|---|
| Route | `/excel-generator` |
| Module | `modules/excel_generator/` |
| Access | all |
| Version | V1.2 |

## Purpose

Generate vendor XML/Excel. Pre-flight against dictionary, golden rules, and CM snapshot diff.

## Approach

Keep pre-flight. Do not emit files that skip validation because “it’s just a template”.

## History

- 2026-08-19: pre-flight validation. Version V1.2.

## Plans

**Parked:** browser-verify `/excel-generator`.

## Watch-outs

Module folder is `excel_generator`; user-facing name is XML Generator. Parser is `/xml-parser`.
