# XML Parser

Parse vendor XML CM dumps; profiles + golden-rule validation.

| | |
|---|---|
| Route | `/xml-parser` |
| Module | `modules/xml_parser/routes.py` |
| Access | all |
| Version | V1.1 |

## Purpose

Upload/parse XML, save/load profiles, validate MO vs dictionary / golden rules.

## Approach

Use `utils/xml_safety.py` (defusedxml). DOCTYPE is allowed via that path — do not switch to raw `xml.etree` for untrusted uploads. Profiles live in the app DB.

## History

- 2026-07-28: DOCTYPE via defusedxml.
- 2026-08-19: Save/Load Profile were 404 — fixed; MO/golden-rule validation on upload.

## Plans

**Parked:** browser-verify `/xml-parser`.

## Watch-outs

XML **Generator** is `/excel-generator`. Names are historical.
