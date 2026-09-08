# Auth, sessions, activation

Not a dashboard tile. Runs on every request before feature code.

| | |
|---|---|
| Login | `routes/auth_routes.py` — cookie `session_token` |
| Activation | `routes/activation_routes.py`, `core/activation_gate.py` |
| Users | `database_enhanced.py` + `connect_app()` |
| Access | `core/module_access.py`, `core/feature_access.py` |

## Purpose

Monthly operator activation lock, login/session, password rotation, CSRF origin check, per-role feature grants.

## Approach

- Copy `login_required` / `admin_required` from `core/radio/web.py` (or the same pattern in the module). Do not invent a third session reader.
- Public allowlist is small: `/health`, `/activation`, `/robots.txt`, login/static. 404 HTML is theme-aware; `/api/*` 404 is JSON.
- `NCM_SKIP_ACTIVATION=1` only for local tests.
- Feature visibility: `NAV_SECTIONS` defaults, overrides in `feature_access` (admin panel).

## History

- 2026-08-31: custom HTML 404, `/robots.txt`, `X-Robots-Tag` on all responses.
- Ongoing: activation gate before SQLite (`install_sqlite_gate` in `app.py` before DB imports).

## Plans

None. Do not weaken activation for convenience on a laptop that will be copied to the server.

## Watch-outs

KPI query strings are stripped from access logs (`ConciseRequestHandler` in `app.py`). Password-rotation hook can 403 APIs when `force_password_change` is set — tests must use a session that is past that gate.
