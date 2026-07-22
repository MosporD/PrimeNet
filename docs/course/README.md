# PrimeNet — A Code-Level Course

A guided, hands-on course for understanding **every part of PrimeNet at the code
level** — written against the real files in this repo, with `file:line`
references you can open as you read.

It's built to be read **in order**. Each lesson assumes the previous ones. By
the end you'll be able to open any of the ~40 modules and know exactly what
you're looking at, why it's shaped that way, and how to change it safely.

> If you only read one page for a quick map, read `docs/ARCHITECTURE.md`.
> This course is the deep version of that map.

---

## How to use this course

1. **Get it running first** (see below). Reading code you can't run is half
   the picture — you want to click the tool while you read its code.
2. Read the lessons in order. Keep the referenced file open in your editor.
3. Do the exercises in Lesson 11 as you go — they're small, real changes.

## Setup & run (do this once)

```bash
# 1. Python deps
pip install -r requirements.txt

# 2. Config
cp .env.example .env
#    edit .env and set (for local dev):
#      NCM_SKIP_ACTIVATION=1      # turn off the license lock
#      FLASK_DEBUG=1              # auto-reload + tracebacks
#      NCM_DISABLE_AUTO_BROWSER=1 # optional, on headless/Linux
#      NCM_DISABLE_LIVE_LOGGER_TERMINAL=1

# 3. Run
python app.py
# → http://localhost:5000/dashboard
```

What happens on boot (all in `app.py`): `.env` loads → the SQLite activation
gate is installed → all ~40 blueprints import and register → the dev server
starts. If activation is skipped, every page is reachable; otherwise you land on
`/activation`.

> **No data yet?** The analytics pages read from SQLite files under
> `databases/` that the ETL pipeline populates. On a fresh clone those are
> mostly empty, so pages render but tables are blank. That's expected — the code
> still runs. Lesson 09 covers how the pipeline fills them.

---

## The curriculum

| # | Lesson | What you'll learn |
|---|---|---|
| 00 | **This page** | Setup, how the course works |
| 01 | [Fundamentals & the app shell](01-fundamentals.md) | Flask, blueprints, the request lifecycle, `app.py` line by line |
| 02 | [Activation & security](02-activation-and-security.md) | The `sqlite3.connect` monkeypatch license gate; CSRF, CSP, input sanitizing |
| 03 | [Auth, sessions & access control](03-auth-sessions-access.md) | `database_enhanced.py`, `auth_routes.py`, `module_access.py`, the decorators |
| 04 | [The data model](04-data-model.md) | `sync_config.py` paths, `db/runtime.py`, PM/metadata schema, the ATTACH+JOIN trick, KPI name resolution |
| 05 | [The shared radio engine](05-radio-engine.md) | `core/radio/*` + `son_analytics/pm_helpers.py`: how "degraded cell" detection actually works |
| 06 | [Anatomy of a module](06-anatomy-of-a-module.md) | `sleeping_cells` end to end; build your own module from scratch |
| 07 | [Module reference (all 40)](07-module-reference.md) | Every module, grouped by family, with its real endpoints and files |
| 08 | [The heavy subsystems](08-heavy-subsystems.md) | `cm_extractor`, `performance`, `network_map`, `sync` — the big four |
| 09 | [The ETL pipeline](09-pipeline.md) | How raw vendor files become SQLite rows |
| 10 | [Frontend & theming](10-frontend.md) | The shared shells, CSS system, constellation background |
| 11 | [Exercises & capstone](11-exercises.md) | Hands-on labs, from one-line tweaks to a new module |

---

## The one idea to hold onto

Almost everything in PrimeNet is the same shape:

```
Browser → app.py (gate/auth/sanitize) → a module route → core/ logic → a SQLite read → JSON → screen
```

Learn that spine once (Lessons 01–06) and the 40 modules become variations on a
theme, not 40 things to memorize.
