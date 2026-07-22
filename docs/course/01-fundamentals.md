# Lesson 01 — Fundamentals & the app shell

**Goal:** understand Flask well enough to read this codebase, then walk `app.py`
top to bottom so you know exactly what happens on every request.

---

## 1.1 The 5 Flask concepts you need

PrimeNet is a **Flask** app. You only need five ideas:

1. **App object** — `app = Flask(__name__)`. The thing that receives HTTP
   requests and routes them to Python functions. Created once in `app.py:27`.

2. **Route / view function** — a Python function decorated with a URL:
   ```python
   @app.route("/health")
   def health_check():
       return jsonify({"status": "ok"})
   ```
   When someone GETs `/health`, Flask calls `health_check()` and sends back what
   it returns. A returned dict-via-`jsonify` becomes a JSON HTTP response.

3. **Blueprint** — a *group* of routes packaged as a unit, so features live in
   their own files instead of one giant `app.py`. Each PrimeNet module defines a
   blueprint and `app.py` registers it:
   ```python
   from modules.sleeping_cells.routes import sleeping_cells_bp   # define elsewhere
   app.register_blueprint(sleeping_cells_bp)                     # plug it in
   ```
   Registering a blueprint = "add all of that module's routes to the app."

4. **Request context** — inside a view function, the globals `request` (incoming
   data), `session`, and `g` (a per-request scratchpad) are available by import
   from `flask`. PrimeNet uses `g` to hand sanitized input to routes (Lesson 02).

5. **`before_request` / `after_request` hooks** — functions that run *before*
   (or *after*) **every** view function. This is where PrimeNet does auth
   gating, input validation, CSRF, and security headers. They're the reason a
   single module route can stay tiny — the cross-cutting work already happened.

That's the whole framework surface you need. Everything else is ordinary Python.

---

## 1.2 `app.py` walked top to bottom

Open `app.py` and follow along. It has five jobs, in this order.

### Job 1 — Boot the environment (lines 14–29)

```python
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from core.activation_gate import install_sqlite_gate
install_sqlite_gate()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024   # 100 MB upload cap
app.config['SECRET_KEY'] = (os.getenv('FLASK_SECRET_KEY') or ... or secrets.token_hex(32))
```

Two things happen **before the app object even exists**, and the order matters:

- **`.env` is loaded first** so that everything downstream can read config
  (including whether activation is required).
- **`install_sqlite_gate()` runs second** — this is the license lock (Lesson
  02). It monkeypatches `sqlite3.connect`, so it must be installed *before* any
  module that opens a database is imported. That's why it's at the very top.

`SECRET_KEY` signs session data; if you don't set one, a random one is generated
per boot (which would invalidate sessions on restart — fine for dev, set it in
prod).

### Job 2 — Register every blueprint (lines 36–115)

```python
from routes.auth_routes import auth_bp
from modules.network_map.routes import network_map_bp
...  # ~40 imports
app.register_blueprint(auth_bp)
app.register_blueprint(network_map_bp)
...  # ~40 registrations
```

This block is the **master index of the entire app**. Every feature is here
twice: once imported, once registered. If a URL 404s, the first thing to check
is whether its blueprint appears in *both* lists.

> **Convention:** adding a module = adding one import line + one
> `register_blueprint` line here. Nothing auto-discovers modules.

### Job 3 — Error handlers (lines 128–136)

```python
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 100MB'}), 413

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500
```

When Flask raises a 413 (upload too big) or a 500 (any uncaught exception),
these return clean JSON instead of an HTML stack trace. The `, 413` / `, 500` is
the HTTP status code — returning `(body, status)` is Flask's tuple form.

### Job 4 — The request-hook stack (lines 242–422)

This is the most important part of `app.py`. These `@app.before_request`
functions run **in definition order** on every request. Read them as a pipeline
each request passes through:

| Order | Function | What it enforces |
|---|---|---|
| 1 | `enforce_monthly_operator_activation` | Not activated → redirect to `/activation` (pages) or 403 (APIs). Allowlist: `/health`, `/activation`, activation APIs, `/static/`. |
| 2 | `validate_and_sanitize_request_input` | Rejects oversized/malformed query, form, JSON; stores cleaned copies on `g.sanitized_*`. |
| 3 | `enforce_csrf_origin_for_cookie_auth` | On POST/PUT/PATCH/DELETE with a session cookie, checks `Origin`/`Referer` is same-origin. |
| 4 | `enforce_password_rotation` | If the user's password is expired/forced, redirect to profile. |

And one `@app.after_request`:

| `set_security_headers` | Adds CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` to every response. |

We dissect hooks 1–3 and the headers in **Lesson 02**, and hook 4 in Lesson 03.
For now, the mental model: **by the time your module's view function runs, the
request is already authenticated-checked, size-checked, sanitized, and
CSRF-checked.** Your route can focus on the feature.

### Job 5 — Run the server (lines 424–455)

```python
if __name__ == '__main__':
    class ConciseRequestHandler(WSGIRequestHandler):
        def log_request(self, code='-', size='-'):
            # strips the ?query string out of access logs
            ...
    app.run(debug=..., host=..., port=..., request_handler=ConciseRequestHandler)
```

`if __name__ == '__main__'` means "only when you run `python app.py` directly"
(not when a WSGI server like gunicorn imports `app`). In production,
`deploy/gunicorn.conf.py` imports the `app` object instead and this block is
skipped.

`ConciseRequestHandler` exists for one real reason: KPI requests carry giant
`?kpis=...` query strings, and without this the access log would be unreadable.
It strips everything after `?` from the logged request line.

---

## 1.3 Trace one request end to end

Let's follow `GET /health` (the simplest route):

1. Request arrives at the dev server (`app.run`, line 450).
2. `before_request` hook 1 runs. `/health` is in the allowlist → returns `None`
   (meaning "don't block, continue"). Hooks 2–4 also pass.
3. Flask matches `/health` to `health_check()` (`app.py:213`).
4. It checks activation, opens the app DB via `db.runtime.connect_app()`, runs
   `SELECT 1`, and returns `jsonify({...})`.
5. `after_request` adds security headers.
6. `ConciseRequestHandler.log_request` logs `"GET /health HTTP/1.1" 200`.

Every request in PrimeNet follows this exact skeleton. The only thing that
changes between features is step 3–4: which view function, and what it reads.

---

## 1.4 A note on `flask.g` and returning `None`

Two Flask idioms you'll see constantly:

- **`before_request` returning `None`** means "allow, keep going." Returning a
  *response* (like `jsonify(...)` or `redirect(...)`) means "stop here, send
  this now" — the view function never runs. That's how the gates block.
- **`g`** is a per-request object that's reset on every request. PrimeNet stashes
  `g.sanitized_json`, `g.sanitized_form`, `g.sanitized_args` so routes can read
  already-cleaned input.

---

## Recap

- PrimeNet is Flask; the only concepts that matter are app, route, blueprint,
  request context, and before/after hooks.
- `app.py` does five things: boot env + install the DB gate, register all
  blueprints, define error handlers, define the request-hook pipeline, run the
  server.
- Every request passes through the same gate/sanitize/CSRF pipeline before
  reaching a feature — which is why feature routes are small.

**Next:** [Lesson 02 — Activation & security](02-activation-and-security.md),
where we open the license gate that hook 1 enforces.
