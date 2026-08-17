# Lesson 10 — Frontend & theming

**Goal:** understand the UI side — the shared templates, the CSS/JS system, the
light/dark theme mechanism, and the constellation dashboard — so you can change
how things look without breaking the shared shells.

Files: `templates/*.html`, `modules/*/templates/`, `static/css/*`,
`static/js/*`, `docs/FRONTEND_THEME.md`.

---

## 10.1 The templates you share

At the top level, `templates/` holds the shells every module leans on:

| Template | Role |
|---|---|
| `dashboard.html` | The landing "constellation deck" — the home page after login. |
| `radio_module.html` | The shared shell for filter-based modules (Lesson 06). |
| `login.html`, `register.html` | Auth pages. |
| `activation.html` | The license-unlock page (Lesson 02). |

Individual modules put their own pages in `modules/<name>/templates/`. A module
either:
- renders the **shared** `radio_module.html` (most optimization modules — no
  local template needed), or
- renders its **own** template for a bespoke UI (map, performance explorer, admin
  panel, etc.).

Flask finds module templates because each blueprint is created with
`template_folder="templates"` (an `AGENTS.md` convention). Both the shared
`templates/` dir and the module's own dir are on the search path.

---

## 10.2 The CSS system

Global stylesheets in `static/css/`:

| File | Scope |
|---|---|
| `common.css` | Base tokens, header, buttons, layout — **loaded by every page**. |
| `constellation.css` | The animated dashboard background + deck theme tokens. |
| `dashboard.css` | Dashboard-specific layout. |
| `radio_modules.css` | The shared filter-module look (used with `radio_module.html`). |
| `auth.css`, `style.css` | Auth pages / legacy. |

The rule from `AGENTS.md` and the current UI-unification effort (see
`checklist.md`): **prefer shared classes over per-module inline styles.** If you
find yourself writing the same styling in two module templates, it belongs in a
shared CSS file.

**Cache-busting:** stylesheet/script links carry a `?v=X.X` query string. Bump it
**only on files you actually changed** so browsers refetch just those — don't
bump everything.

JS in `static/js/`: `common.js` (loaded everywhere — theme toggle, chart theme
sync, header injection), `constellation.js` (the dashboard background animation),
`radio_modules.js` (the shared filter-module behavior), `chart.umd.min.js`
(Chart.js, vendored locally so the CSP doesn't need to allow a CDN),
`saved_views.js`, `app.js`.

---

## 10.3 The theme system (light/dark) — read `docs/FRONTEND_THEME.md`

This is the one frontend subsystem with real rules, because it's easy to break.
The mechanism:

| Piece | Where | Role |
|---|---|---|
| Theme state | `body.dark-mode` class | **The primary switch** — all CSS keys off this. |
| HTML attribute | `documentElement[data-theme]` | Secondary hook for token overrides. |
| Persistence | `localStorage["primenet-theme"]` | Saved preference (`dark`/`light`). |
| Toggle button | `#dark-mode-btn` | Injected by `common.js` into the header. |
| Init | `common.js` on `DOMContentLoaded` | Applies the saved theme on every load. |
| Chart sync | `_syncChartTheme()` in `common.js` | Repaints Chart.js instances on theme change. |
| Event | `primenet:theme-change` | `{detail:{theme}}` — module JS can listen. |

**The rules that keep it working:**

1. **Never build your own dark-mode toggle in a module.** Always load `common.js`
   so the *one* global toggle + persistence apply. A second toggle desyncs the
   state.
2. **Key your CSS off `body.dark-mode`**, e.g.
   `body.dark-mode .my-card { background: #1a1a2e; }`.
3. If your module draws charts, listen for `primenet:theme-change` (or rely on
   `_syncChartTheme`) so they repaint correctly.

Every standalone module page should wire, in order (from `FRONTEND_THEME.md`):

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/common.css') }}?v=X.X">
<link rel="stylesheet" href="{{ url_for('my_module.static', filename='my_module.css') }}?v=X.X">
<script src="{{ url_for('static', filename='js/common.js') }}?v=X.X"></script>
<!-- module JS after common.js -->
```

`common.css`/`common.js` **first**, module assets after — so module styles can
override base tokens and the global JS is initialized before module JS runs.

---

## 10.4 The constellation dashboard

`dashboard.html` + `constellation.js` + `constellation.css` render the animated
"constellation deck" landing page. A few things to know:

- The constellation background is **always dark** (it's a starfield); the rest of
  the dashboard follows `body.dark-mode`.
- The deck's tiles are the module links — filtered by role via
  `navigation_sections_for_role(user)` from `core/module_access.py` (Lesson 03).
  So the dashboard and the access rules can't disagree.
- `static/images/external-tools/` holds icons for links out to other systems
  (NetAct, U2020, GIS, TEMS, …) shown on the dashboard.

`dashboard.html` is a **large** template — the `AGENTS.md` watch-out applies:
edit targeted sections, avoid full-file rewrites, and lean on the constellation
CSS/JS as the single source of theme tokens.

---

## 10.5 The current frontend effort (context)

`checklist.md` + `progress.md` show the in-flight work is a **UI-unification
pass**: get every module template loading `common.css`, using consistent
header/back-link patterns, and the shared shells — removing duplicated inline
styles. If you're picking up frontend work, that's the active scope, and it's
explicitly *not* backend/pipeline changes. The "definition of done" checklist
there is a good spec to work against.

---

## 10.6 How a page actually renders (tying it together)

For a shared-shell module (e.g. `/sleeping-cells`):

1. Server: the page route renders `radio_module.html` with `module_title`,
   `api_url`, etc. (Lesson 06). HTML comes back with `common.css` +
   `radio_modules.css` loaded.
2. Browser: `common.js` applies the saved theme, injects the header + dark-mode
   button.
3. `radio_modules.js` reads the `api_url`, builds the filter query string from the
   filter bar, `fetch()`es it.
4. The server API returns `{success, issues, summary}`; the JS renders the summary
   chips + results table.
5. Change a filter → step 3–4 repeat. Toggle theme → `primenet:theme-change` fires,
   CSS + charts repaint.

For a bespoke module (map, performance), replace steps 3–4 with that module's own
JS, but steps 1–2 (shared shell chrome + theme) are identical.

---

## 10.7 UI zoom (`--ui-zoom`)

PrimeNet is laid out at **67% of CSS pixels** so a 100% Chrome window matches
~67% browser zoom, but still **fills the viewport**. `static/css/common.css`:

```css
:root {
    --ui-zoom: 0.67;
    --ui-vw: calc(100vw / var(--ui-zoom));
    --ui-vh: calc(100vh / var(--ui-zoom));
}
body {
    zoom: var(--ui-zoom);
    width: var(--ui-vw);
    min-height: var(--ui-vh);
}
```

Full-page layouts must use `var(--ui-vh)` / `var(--ui-vw)`, **not** `100vh` /
`100vw`. Plain `100vh` under `zoom` leaves a gap or overflows — that was the
Developer Documentation bug. Pointer math for canvases/charts goes through
helpers in `common.js` / `constellation.js` (`viewportCssSize`,
`patchChartJsForUiZoom`).

---

## Recap

- `templates/` holds shared shells; modules add their own only for bespoke UIs.
  Blueprints use `template_folder="templates"`.
- `common.css`/`common.js` load everywhere; `radio_modules.*` power the shared
  filter shell; charts are vendored locally (CSP-friendly).
- Theme = `body.dark-mode` + `localStorage` + one global toggle in `common.js`.
  Never roll your own toggle; key CSS off `body.dark-mode`.
- Global scale is `--ui-zoom: 0.67`; full-height pages use `--ui-vh`, not `100vh`.
- The dashboard deck reads the same role-filtered nav as access control.
- Current scope is UI unification — see `checklist.md`.

**Next:** [Lesson 11 — Exercises & capstone](11-exercises.md).
