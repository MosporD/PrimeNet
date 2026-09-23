# Auth, sessions, activation — progress

Detailed dated log for this blueprint. Brief: [auth-activation.md](auth-activation.md).
Root journal (topics only): [../../progress.md](../../progress.md).

---
## 2026-09-20 (Central SSO + portal allow-list)

- Done: Shared nexus_session cookie (+ optional NEXUS_COOKIE_DOMAIN); PrimeNet ncm_users.db is the only identity store.
- Done: users.allowed_portals; NexusCore tower filters cards; PrimeNet/NexPulse redirect unauthenticated users to NexusCore login.
- Done: Tests in core/platform/test_platform.py.
- NEXT: Grant NexPulse on existing marketing users via Admin Portals; set NEXUS_COOKIE_DOMAIN on the server when portals use subdomains.

## From brief History (migrated 2026-09-17)

- 2026-08-31: custom HTML 404, /robots.txt, X-Robots-Tag on all responses.
- Ongoing: activation gate before SQLite (install_sqlite_gate in app.py before DB imports).
