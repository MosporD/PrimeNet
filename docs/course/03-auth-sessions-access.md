# Lesson 03 — Auth, sessions & access control

**Goal:** understand who a "user" is, how login/sessions work, and how the app
decides which of the ~40 tools each role can reach.

Files: `database_enhanced.py`, `routes/auth_routes.py`, `core/module_access.py`,
`core/feature_access.py`, `core/user_vendor_credentials.py`, `core/radio/web.py`.

---

## 3.1 Where users live — `database_enhanced.py`

This ~1000-line file is the **user/session/task database layer**. It talks to
`ncm_users.db` (path constant `NCMUSERS_DB` from `sync_config.py`). It has no
Flask in it — just functions that read/write SQLite. The important ones:

| Function | Line | Purpose |
|---|---|---|
| `init_db()` | 40 | Creates the users/sessions/tasks tables if missing. |
| `create_user(...)` | 278 | Insert a user (password stored hashed). |
| `hash_password` / `verify_password` | 259 / 265 | Password hashing (PBKDF2). |
| `authenticate_user(username, password)` | 305 | Check credentials, return the user row or `None`. |
| `create_session(user_id)` | 497 | Make a random `session_token`, store it, return it. |
| `get_user_by_session(token)` | 522 | Token → user. **This is the function the whole app uses to know "who is this request."** |
| `delete_session(token)` | 542 | Logout. |
| `is_password_change_required(user, max_days=60)` | 1023 | Drives the password-rotation hook from Lesson 01. |

### The user shape gotcha (important)

A user comes back in **two possible shapes** depending on the code path:

- a **dict** (`{"id":..., "username":..., "role":...}`), or
- a **positional tuple** (a raw SQLite row) where **`user[6]` is the role**.

You'll see helper functions everywhere that tolerate both, e.g.
`core/radio/web.py:_role`:

```python
def _role(user) -> str:
    if isinstance(user, dict):
        return str(user.get("role") or "").strip().lower()
    return str(user[6] or "").strip().lower()   # tuple: index 6 == role
```

When you touch user objects, **mirror this dual handling** or you'll crash on
one of the two paths. Roles in the system: `admin` (owner), `noc_sys` (NOC SYS),
`ran_config_user` (RNC User), and `user`.

---

## 3.2 Login / logout — `routes/auth_routes.py`

This blueprint (`auth_bp`) owns the auth pages and the dashboard's data APIs.

### The login flow (`login()`, line 240)

1. Read username/password from the JSON body.
2. **Rate-limit check** — `_login_rate_limit_remaining(ip, username)` (line 42).
   PrimeNet keeps an in-memory `deque` of recent failures per IP+username and
   blocks after too many. `_record_login_failure` / `_clear_login_failures`
   maintain it. (In-memory means it resets on restart and isn't shared across
   processes — fine for a single-process deployment.)
3. `authenticate_user(...)` verifies the password.
4. On success: `create_session(user_id)` → set the token as an **HttpOnly
   cookie** named `session_token`.
5. Return JSON; the browser now sends that cookie on every request.

### Everything hangs off the `session_token` cookie

There is no server-side "logged-in" flag beyond the sessions table. Auth is
simply: *does this request carry a `session_token` cookie that maps to a user?*
Every protected route answers that with `get_user_by_session(...)`.

### The dashboard data APIs (same file)

`auth_routes.py` also serves the landing dashboard's widgets:
`/api/dashboard/pm-health`, `/neighbor-health`, `/network-activity`,
`/site-map`, plus `/api/global-search` and `/api/navigation/allowed`. These are
here (rather than in a module) because the dashboard is "home base." Skim
`get_operational_site_stats` (line 101) and `dashboard_site_map` (line 441) to
see the JOIN-against-metadata pattern you'll meet properly in Lesson 04.

---

## 3.3 The decorators feature modules actually use — `core/radio/web.py`

This tiny file (95 lines) is the auth toolkit every module imports. Two
decorators:

```python
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user          # stash for the view
        return f(*args, **kwargs)
    return decorated
```

`admin_required` is the same but adds `if _role(user) != "admin": return 403`.
A route decorated with `@admin_required` is simply unreachable by non-admins.

Also here:
- `get_current_user()` — token → user (or `None`).
- `format_user(user)` — normalize either user shape to a small dict for
  templates.
- `query_filters(default_limit=200)` — **parses the standard filter set** every
  radio module shares from the query string:

  ```python
  {
    "area":       request.args.get("area") or "all",
    "vendor":     (request.args.get("vendor") or "all").lower(),
    "technology": request.args.get("technology") or request.args.get("rat") or "all",
    "severity":   request.args.get("severity") or "all",
    "search":     request.args.get("q") or request.args.get("search") or "",
    "limit":      min(1000, max(1, int(request.args.get("limit") or 200))),
  }
  ```

  This is why every optimization module accepts the same
  `?area=&vendor=&technology=&severity=&q=&limit=` URL. One helper, one
  contract.
- `json_error(exc, status=500)` — uniform `{"success": False, "error": ...}`
  response. Every API `except` block calls this.

---

## 3.4 Who can see what — `core/module_access.py`

This is the **single source of truth for navigation and access**. At its heart
is a declarative list, `NAV_SECTIONS` (line 11):

```python
NAV_SECTIONS = [
  {"title": "Overview & Performance", "links": [
      {"label": "Dashboard",            "href": "/dashboard",  "visibility": "all"},
      {"label": "Huawei PM Query Studio","href": "/performance-analytics", "visibility": "admin"},
      ...
  ]},
  {"title": "Radio Optimization", "links": [ ... mostly "admin" ... ]},
  {"title": "Configuration",      "links": [ ... ]},
  {"title": "Administration",     "links": [
      {"label": "Admin Panel", "href": "/admin-panel?section=user-admin", "visibility": "admin_or_noc"},
      ...
  ]},
]
```

`visibility` has three values:
- `all` — any logged-in user,
- `admin` — owner only,
- `admin_or_noc` — admin **or** the `noc_sys` role.

This one list does **two** jobs:

1. **Renders the menu** — `navigation_sections_for_role(user)` (line 128) filters
   the sections to just the links a role may see. The dashboard calls this so
   users only see tools they can open.
2. **Enforces access** — `href_allowed_for_role(href, user)` (line 155) and
   `enforce_module_access(href, user)` (line 95) check whether a role may reach a
   given path, returning a redirect (pages) or 403 (APIs) when not.

`module_access_before_request(href)` (line 110) is a ready-made blueprint hook:
give it the module's href and it does the whole "get the session user, then
enforce" dance. Some modules wire it as a `before_request`; the radio modules
instead lean on `@admin_required`. Both end up enforcing the same *default* rule.

> **Defaults vs overlay:** `NAV_SECTIONS` is still the place you add a *new*
> tool. Day-to-day "who can open this?" is edited in the **Admin Panel**
> (`core/feature_access.py`). Owner (`admin`) is always allowed and cannot be
> revoked. `/dashboard`, `/profile`, `/admin-panel` are locked. Until someone
> saves an override, behaviour matches `NAV_SECTIONS` exactly.
>
> **Gotcha:** several modules still wrap the page in `@admin_required` *and* the
> feature-access hook (Nokia Load Balancing is one). Opening that href for
> `ran_config_user` in the admin panel will show the dashboard card, but the
> decorator still 403s non-owners. If you mean to open a tool, drop
> `@admin_required` and keep the `before_request` hook.

---

## 3.6 Per-user vendor credentials

NetAct / U2020 passwords are no longer only in `.env`.
`core/user_vendor_credentials.py` stores per-user secrets (used by CM Extractor,
RET, Load Balancing). Users edit them on `/profile`. The Flask `SECRET_KEY` must
be set (app config is enough — see the 2026-07-22 fix) or save fails.

---

## 3.7 Putting it together

A protected page request, e.g. `GET /sleeping-cells`:

1. `app.py` gates run (activation, sanitize, CSRF, password rotation).
2. Flask calls the view, which is wrapped in `@admin_required`.
3. `admin_required` reads `session_token` → `get_user_by_session` → checks
   `_role(user) == "admin"`. Non-admin → 403 / redirect. Admin → continue.
4. The view runs and renders the page.

For "does this link even appear in the menu," `navigation_sections_for_role`
reads `NAV_SECTIONS` **plus** `feature_access` overrides. Menu and route
enforcement agree *when the module uses `module_access_before_request`*. They
disagree if the view still has `@admin_required` (see the gotcha above).

---

## Recap

- Users/sessions live in `database_enhanced.py` → `ncm_users.db`. Auth is a
  `session_token` HttpOnly cookie resolved by `get_user_by_session`.
- A user object may be a dict *or* a tuple (`user[6]` = role) — always handle
  both.
- `core/radio/web.py` gives modules `@login_required` / `@admin_required`,
  `query_filters()`, and `json_error()`.
- `core/module_access.py`'s `NAV_SECTIONS` is the *default* menu + gate. Runtime
  grants live in `core/feature_access.py` (Admin Panel). Some routes still use
  `@admin_required` on top of that.

**Next:** [Lesson 04 — The data model](04-data-model.md) — the databases every
one of these routes reads from.
