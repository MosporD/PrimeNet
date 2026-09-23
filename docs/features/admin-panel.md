# Admin Panel

Users, roles, portal allow-list, feature-access grants.

| | |
|---|---|
| Route | /admin-panel (often ?section=user-admin) |
| Module | modules/admin_panel/routes.py |
| Access | admin_or_noc |
| Version | V1.0 |

## Purpose

Create/disable users, reset password, **portal checkboxes** (llowed_portals), **feature_access** matrix (core/feature_access.py).
Owner also manages Data Sync, API connections, and **PM Plus Rules** (Nokia catalog import + aggregation overrides for Performance Explorer Plus).

## Approach

Visibility defaults: core/module_access.py. Overrides stored in app DB. Admin always sees everything. Do not hide tiles only in dashboard.html — the access layer will fight you.
Portal keys: primenet, 
expulse, sales, support — gates tower entry, not in-portal RBAC.

## Progress

Dated work log: [dmin-panel.progress.md](admin-panel.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

NOC SYS can administer users; it is not a full admin for every radio tile unless granted.
