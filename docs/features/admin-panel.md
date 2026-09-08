# Admin Panel

Users, roles, feature-access grants.

| | |
|---|---|
| Route | `/admin-panel` (often `?section=user-admin`) |
| Module | `modules/admin_panel/routes.py` |
| Access | admin_or_noc |
| Version | V1.0 |

## Purpose

Create/disable users, reset password, **feature_access** matrix (`core/feature_access.py`).

## Approach

Visibility defaults: `core/module_access.py`. Overrides stored in app DB. Admin always sees everything. Do not hide tiles only in `dashboard.html` — the access layer will fight you.

## History

Activity log / feature grants evolved with the radio pack (2026-08).

## Plans

None parked.

## Watch-outs

NOC SYS can administer users; it is not a full admin for every radio tile unless granted.
