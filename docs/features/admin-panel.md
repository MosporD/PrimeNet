# Admin Panel

Engineering ops admin on PrimeNet (sync, APIs, PM Plus, activity).

| | |
|---|---|
| Route | /admin-panel (default `?section=data-sync`) |
| Module | modules/admin_panel/routes.py |
| Access | admin (Owner) |
| Version | V1.0 |

## Purpose

Owner manages Data Sync, API connections, PM Plus Rules, Ops Alerts (RET/CM), and activity.
**Users, portal allow-list, and module access** live on NexusCore Platform Admin (`/admin`) — see [platform-admin.md](platform-admin.md).

## Approach

Visibility defaults: core/module_access.py (Module Access matrix on NexusCore). Engineering Admin is Owner-only.
Legacy `/api/admin/users*` and `/api/admin/feature-access*` return 410 with redirect to NexusCore `/admin`.

## Progress

Dated work log: [admin-panel.progress.md](admin-panel.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.

## Plans

None parked.

## Watch-outs

NOC SYS uses NexusCore Platform Admin for users; they no longer open Engineering Admin.
