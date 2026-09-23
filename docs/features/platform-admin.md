# Platform Admin

NexusCore identity, portal allow-list, and PrimeNet module-access matrix.

| | |
|---|---|
| Route | /admin (NexusCore) |
| Module | modules/platform_admin/routes.py |
| Access | admin_or_noc (Owner: users + module access; NOC: users) |
| Version | V1.0 |

## Purpose

Central place on the portal tower for creating users, roles, portal grants (`allowed_portals`), and the PrimeNet Feature/Module Access matrix (`feature_access`).

## Approach

Registered on `nexuscore_app.py`. Reuses `database_enhanced` users DB and `core/feature_access.py` (PrimeNet app DB via shared `NEXUS_DATA_ROOT`). Entry: portals topbar **Admin** for Owner/NOC.

## Progress

Dated work log: [platform-admin.progress.md](platform-admin.progress.md).

## Plans

None parked.

## Watch-outs

Engineering ops (sync, vendor APIs, PM Plus) stay on PrimeNet `/admin-panel`.
