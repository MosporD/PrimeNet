# Lesson 02 — Activation & security

**Goal:** understand the license/activation gate (the most unusual piece of the
codebase) and the three security hooks that wrap every request.

Files: `core/activation_gate.py`, `core/license_client.py`, `app.py`
(the `before_request`/`after_request` block), `utils/input_safety.py`.

---

## 2.1 The problem activation solves

PrimeNet is a licensed product. The owner wants it to **refuse to run** unless
it's been unlocked — either with a local password or a blessing from a remote
license server. The tricky requirement: the lock has to be *impossible to
forget*. If a single module opened the database without checking the license,
the lock would leak.

The solution in `core/activation_gate.py` is clever and worth understanding.

---

## 2.2 The `sqlite3.connect` monkeypatch

All of PrimeNet's data is in SQLite. So the gate hooks the **one function every
data path must call**: `sqlite3.connect`. See `install_sqlite_gate`
(`core/activation_gate.py:328`):

```python
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect   # save the real one

def install_sqlite_gate() -> None:
    global _SQLITE_GATE_INSTALLED
    if _SQLITE_GATE_INSTALLED:
        return
    def gated_connect(database, *args, **kwargs):
        if not is_bypass_enabled() and not is_activated():
            require_activation()                 # raises ActivationRequired
        return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)
    sqlite3.connect = gated_connect              # ← replace it globally
    _SQLITE_GATE_INSTALLED = True
```

After this runs, **every** `sqlite3.connect(...)` call anywhere in the
process — in your code, in a library, in a script — first checks activation and
raises `ActivationRequired` if the app isn't unlocked. You cannot accidentally
bypass it, because you can't open a database without going through it.

This is why:

- `app.py:24` calls `install_sqlite_gate()` **before importing any module** that
  might touch a DB.
- `db/runtime.py:16` calls it **again** defensively. The `_SQLITE_GATE_INSTALLED`
  flag makes the second call a no-op (idempotent), so double-install is safe.

> **Dev bypass:** `is_bypass_enabled()` returns true when `NCM_SKIP_ACTIVATION=1`
> (`core/activation_gate.py:63`). With that env var, `gated_connect` skips the
> check entirely. That's the switch you flip for local development.

---

## 2.3 Two activation modes

`is_activated()` (line 266) branches on mode:

```python
def is_activated() -> bool:
    if is_bypass_enabled():          # NCM_SKIP_ACTIVATION=1 → always on
        return True
    if _remote_mode():               # NCM_LICENSE_SERVER_URL set → ask the server
        from core.license_client import is_activated as remote_activated
        return remote_activated()
    return _local_is_activated()     # else → check the local signed state file
```

### Local mode (default, no server)

- You set a password once: `python scripts/set_activation_password.py`. That
  stores a **PBKDF2-SHA256 hash** (600,000 iterations — see `_PBKDF2_ITERATIONS`,
  line 47) plus an HMAC **signing key**.
- Unlocking (`_local_unlock`, line 229) verifies the password, then writes a
  signed state file `.ncm_activation_state` containing an expiry timestamp and an
  HMAC signature over that expiry (`_sign_payload`, line 124).
- `_verify_local_state` (line 160) re-checks on every `is_activated()` call: the
  expiry must be in the future **and** the signature must match. Tampering with
  the file's expiry breaks the signature → still locked. Default active period is
  180 days (`_DEFAULT_ACTIVATION_PERIOD_DAYS`, line 31).

The password check itself (`_local_verify_password`, line 238) is a constant-time
compare (`hmac.compare_digest`) against the stored PBKDF2 hash — no timing leak.

### Remote mode (recommended for real deployments)

When `NCM_LICENSE_SERVER_URL` is set, `_remote_mode()` is true and all the
public functions delegate to `core/license_client.py`, which talks to a separate
license service that holds the private signing key. The app never has the key —
it only verifies signed tokens. This is why the docstring at the top of
`activation_gate.py` calls remote mode "recommended."

### The public API (bottom of the file)

Everything funnels through these, so the rest of the app never cares which mode
is active:

| Function | Meaning |
|---|---|
| `is_configured()` | Is activation set up at all? |
| `is_activated()` | Is it currently unlocked? |
| `activation_status()` | Full status dict (mode, expiry, days remaining) — used by `/activation` UI and `/health`. |
| `unlock(password)` | Attempt an unlock. |
| `require_activation()` | Raise `ActivationRequired` if not activated. Called by `db/runtime.py` connect helpers. |

---

## 2.4 How the gate reaches the user

Two layers enforce it:

1. **The HTTP layer** — `app.py:242` `enforce_monthly_operator_activation`
   before-hook: if `is_activated()` is false, redirect page requests to
   `/activation` and return 403 JSON for `/api/*`. A small allowlist keeps the
   activation page and `/health` reachable while locked.
2. **The data layer** — the `sqlite3.connect` monkeypatch, as a backstop. Even
   if some route slipped past the HTTP check, the moment it touches the DB it
   raises `ActivationRequired`.

Belt and suspenders. The HTTP layer gives a nice redirect; the data layer
guarantees no data leaks.

The `/activation` page and its APIs live in `routes/activation_routes.py` (59
lines): `GET /activation` renders the unlock page, `POST /api/activation/unlock`
calls `unlock(password)`, `GET /api/activation/status` returns
`activation_status()`.

---

## 2.5 The security hooks (the rest of the pipeline)

Back in `app.py`, three more `before_request` hooks harden every request.

### Input sanitizing — `validate_and_sanitize_request_input` (line 270)

This rejects abusive payloads and hands clean data to routes:

- Query string over 4 KB → `413`.
- JSON body over the size/item budget → `413`. Note the special case: CM-extractor
  APIs get **8 MB / 100k items**, everyone else **1 MB / 5k items** (lines
  280–282) — because config exports are genuinely huge.
- Malformed JSON → `400`.
- Clean copies are stored on `g.sanitized_json`, `g.sanitized_form`,
  `g.sanitized_args`.

The actual cleaning is in `utils/input_safety.py`: `sanitize_json` walks the
structure enforcing `max_depth`, `max_items`, `max_key_len`, `max_str_len`, and
`sanitize_mapping_values` does the same for query/form pairs. This caps the blast
radius of a malicious or runaway request before any feature code sees it.

### CSRF — `enforce_csrf_origin_for_cookie_auth` (line 338)

CSRF (cross-site request forgery) is when another site tricks your logged-in
browser into POSTing to PrimeNet. The defense here is **origin checking**:

```python
if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
    return None                          # reads are safe, skip
token = request.cookies.get("session_token")
if not token:
    return None                          # not cookie-authed, skip
# else: Origin (or Referer) header MUST match our own host, or 403
```

Only state-changing methods on cookie-authenticated requests are checked. If the
`Origin` header is present and cross-origin → `403`. If there's no `Origin` and
no `Referer` at all → also `403` (a real browser always sends one).

### Security headers — `set_security_headers` (line 403, after_request)

Sets defensive headers on every response. The big one is the **Content Security
Policy**:

```python
"default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
"img-src 'self' data: blob: https://*.tile.openstreetmap.org ... arcgisonline.com; ..."
```

Read this as a whitelist of what the browser is allowed to load. It permits:
- scripts/styles from our own host + `unpkg.com` (where Leaflet and a few libs
  come from),
- map tile images from OpenStreetMap and ArcGIS (the mapping modules need them).

If you ever add a new third-party asset and it's silently blocked in the browser
console, this CSP is why — you'd add its host here.

---

## Recap

- The activation gate makes the license unforgettable by monkeypatching
  `sqlite3.connect` — no DB access without an unlock. `NCM_SKIP_ACTIVATION=1`
  turns it off for dev.
- Local mode = PBKDF2 password + HMAC-signed expiry file; remote mode = a
  separate signing server. One public API hides the difference.
- Three more hooks sanitize input (with a bigger budget for CM-extractor), block
  cross-origin state changes, and set a strict CSP that whitelists unpkg + map
  tiles.

**Next:** [Lesson 03 — Auth, sessions & access control](03-auth-sessions-access.md).
