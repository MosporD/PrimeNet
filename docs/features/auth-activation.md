# Auth, sessions, activation

Not a dashboard tile. Runs on every request before feature code.

| | |
|---|---|
| Login | NexusCore `/login` — shared cookie `nexus_session` (`core/platform/session.py`) |
| Users | `database_enhanced.py` + PrimeNet `ncm_users.db` (central identity) |
| Portals | `users.allowed_portals` via `core/platform/portal_access.py` |
| Activation | `routes/activation_routes.py`, `core/activation_gate.py` |
| Feature access | `core/module_access.py`, `core/feature_access.py` (inside PrimeNet) |

## Purpose

Monthly operator activation lock, single NexusCore login, portal allow-list, password rotation, CSRF origin check, per-role feature grants inside Engineering.

## Approach

- Copy `login_required` / `admin_required` from `core/radio/web.py` (or the same pattern in the module). Do not invent a third session reader — use `get_session_token()`.
- Public allowlist is small: `/health`, `/activation`, `/robots.txt`, login/static. 404 HTML is theme-aware; `/api/*` 404 is JSON.
- `NCM_SKIP_ACTIVATION=1` only for local tests.
- Portal entry: Admin Panel portal checkboxes. Feature visibility: `NAV_SECTIONS` + `feature_access`.
- `NCM_ALLOW_LOCAL_LOGIN=1` only for emergency PrimeNet/NexPulse login without the lobby.

## Progress

Dated work log: [`auth-activation.progress.md`](auth-activation.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None. Do not weaken activation for convenience on a laptop that will be copied to the server.

## Watch-outs

KPI query strings are stripped from access logs (`ConciseRequestHandler` in `app.py`). Password-rotation hook can 403 APIs when `force_password_change` is set — tests must use a session that is past that gate. Existing users with empty `allowed_portals` keep Engineering (`primenet`); Owners default to live portals.
