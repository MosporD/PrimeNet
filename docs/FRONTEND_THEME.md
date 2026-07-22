# PrimeNet frontend theme guide

How light/dark mode works across the UI, and how to build or fix module pages so dark mode looks correct.

---

## Mandatory for every new module

Dark mode is **not automatic** for new modules. `common.css` covers shared primitives (header, inputs, `.panel`, `.card`, tables), but **module-specific CSS almost always needs explicit dark rules**. Shipping a module without them is a known regression pattern.

Before marking a module done:

1. Load `common.css` then module CSS, and `common.js` (see [Required template wiring](#required-template-wiring)).
2. Add `<body class="your-module-page">` for scoped overrides.
3. In module CSS, define light tokens on `:root` and override them under `body.dark-mode.your-module-page` (see [Recommended patterns](#recommended-patterns-for-new-module-css)).
4. Run the [Checklist — new module page](#checklist--new-module-page) in **both** light and dark.
5. Run the [Quick audit command](#quick-audit-command) on your new CSS file — zero hits for naked `#fff` / `#ffffff` without a dark path.

**Do not merge** a new module if cards, toolbars, or custom widgets stay white in dark mode.

---

## How theme switching works

| Piece | Location | Role |
|-------|----------|------|
| Theme state | `body.dark-mode` class | **Primary switch** — all CSS should key off this |
| HTML attribute | `document.documentElement[data-theme="dark\|light"]` | Secondary hook for future token overrides |
| Persistence | `localStorage` key `primenet-theme` | Saved user preference (`dark` or `light`) |
| Legacy key | `localStorage` key `darkMode` | Still written for older pages (`true` / `false`) |
| Toggle UI | `#dark-mode-btn` | Injected by `static/js/common.js` into the header |
| Init | `common.js` → `_applyTheme(_preferredTheme())` on `DOMContentLoaded` | Applies saved theme on every page load |
| Chart sync | `_syncChartTheme()` in `common.js` | Updates Chart.js defaults and live instances |
| Custom event | `primenet:theme-change` | `{ detail: { theme: 'dark' \| 'light' } }` — listen in module JS |

**Rule:** Never implement a separate dark-mode toggle in a module. Always load `common.js` so the global toggle and persistence work.

---

## Required template wiring

Every standalone module page should include:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/common.css') }}?v=X.X">
<link rel="stylesheet" href="{{ url_for('my_module.static', filename='my_module.css') }}?v=X.X">
<!-- module CSS after common.css -->

<script src="{{ url_for('static', filename='js/common.js') }}?v=X.X"></script>
<!-- module JS after common.js -->
```

Optional shared layouts:

- **Radio filter modules** — extend `templates/radio_module.html` and use `static/css/radio_modules.css`
- **Dashboard** — `static/css/dashboard.css` + `static/css/constellation.css` (constellation deck is always dark; rest of dashboard follows `body.dark-mode`)

Bump `?v=` only on files you actually changed.

---

## CSS architecture (layers)

Apply styles in this order — lower layers should not be fighting upper layers.

### 1. `static/css/common.css` (global baseline)

Provides:

- Shared header, buttons, tables, forms, status messages
- **`body.dark-mode` defaults** for page background, text, inputs, links, `.panel`, `.section`, `.card`, tables
- **Dark tokens** on `body.dark-mode`:

```css
--dm-bg: #0f1722;
--dm-panel: #182230;
--dm-panel-2: #1b2736;
--dm-panel-3: #223246;
--dm-border: #304258;
--dm-text: #e8eef7;
--dm-muted: #a9b7c9;
--dm-link: #8bc1ff;
--dm-input: #101b28;
```

- A long **allowlist** of panel/surface class names that automatically get dark surfaces (`.toolbar`, `.report-card`, `.sh-section`, `.cm-card`, etc.)

If your module uses one of those standard class names, dark mode may already work with no extra CSS.

### 2. Module CSS (`modules/<name>/static/*.css`)

Module-specific layout and components. **This is where most dark-mode gaps come from** when light-only colors are hardcoded (`background: #fff`, `color: #2c3e50`).

### 3. Page-specific overrides

Some modules add `body.dark-mode.<page-class>` rules (e.g. `body.dark-mode.sector-health-page`). Use a page class on `<body>` when module styles need scoped dark fixes.

---

## Brand palette (light mode)

Use these for new light-mode UI (aligned with dashboard / header gradient):

| Token | Hex | Usage |
|-------|-----|--------|
| Page background | `#f5f7fa` | `body`, `.main-content` |
| Surface | `#ffffff` | Cards, panels, tables |
| Surface elevated | `#f4f6f8` / `#eef5fc` | Toolbars, subtle strips |
| Primary | `#7fa6c2` | Accents, links in header context |
| Primary dark | `#6d95b3` | Button text on white header buttons |
| Text | `#2c3e50` | Headings, body |
| Text muted | `#7f8c8d` / `#5c6773` | Labels, hints, captions |
| Border | `#d6e6f5` / `#dde1e6` | Cards, inputs |
| Header gradient | `linear-gradient(135deg, #b4cde0 0%, #8fb1ca 55%, #7fa6c2 100%)` | Top bar (from `common.css`) |

**Network Health** documents the same set as `--pn-*` in `modules/network_health/static/network_health.css` — good reference for a token-based module.

---

## Dark mode palette

When `body.dark-mode` is active:

| Role | Hex | Notes |
|------|-----|--------|
| Page background | `#121821` | Set in `common.css` |
| Panel / card | `#182230` | `--dm-panel` |
| Elevated panel | `#1b2736` / `#223246` | Hover, nested surfaces |
| Border | `#304258` / `#2f4056` | `--dm-border` |
| Text | `#e7edf5` / `#e8eef7` | `--dm-text` |
| Muted text | `#a9b7c9` / `#b8c4d6` | `--dm-muted` |
| Links | `#7db7ff` / `#8bc1ff` | `--dm-link` |
| Inputs | `#1a2432` bg, `#304158` border | `--dm-input` |
| Header | `#182533` → `#111924` gradient | Replaces light blue gradient |

Status colors (dark):

- Success: bg `#1d3c2d`, text `#99e2b1`
- Error: bg `#472328`, text `#ffb3be`
- Info: bg `#1f3342`, text `#a8d5ef`

---

## Recommended patterns for new module CSS

### Prefer CSS variables with fallbacks

Define light tokens on `:root` (or the page wrapper), override under `body.dark-mode`:

```css
:root {
    --mod-surface: #ffffff;
    --mod-border: #dde1e6;
    --mod-text: #2c3e50;
    --mod-muted: #5c6773;
}

body.dark-mode {
    --mod-surface: var(--dm-panel, #182230);
    --mod-border: var(--dm-border, #304258);
    --mod-text: var(--dm-text, #e8eef7);
    --mod-muted: var(--dm-muted, #a9b7c9);
}

.my-toolbar {
    background: var(--mod-surface);
    border: 1px solid var(--mod-border);
    color: var(--mod-text);
}
```

Sector Health uses `--surface-elevated`, `--border-color`, `--text-muted` with fallbacks — but **does not define dark values for those vars**, so it also needs explicit `body.dark-mode.sector-health-page` rules. Prefer overriding tokens on `body.dark-mode` once instead of many `!important` rules.

### Reuse standard structural classes

Prefer classes already styled in `common.css`:

- `.panel`, `.section`, `.card`, `.form-card`, `.table-wrap`
- `.btn-primary`, `.btn-secondary`, `.status-message`
- `.field-hint`, `.section-description`

Then add module-specific classes only for layout, not for base colors.

### Avoid

- `background: #fff` / `color: #2c3e50` without a dark counterpart
- Inline `style="background:..."` on dynamic HTML
- Light-only box shadows (`rgba(0,0,0,0.08)`) with no dark adjustment
- Separate theme toggles or duplicate `localStorage` keys
- `!important` unless overriding third-party widgets (use sparingly)

### Page body class

Add a scoped class for module-specific dark rules:

```html
<body class="my-module-page">
```

```css
body.dark-mode.my-module-page .my-custom-widget { ... }
```

---

## Chart.js modules

`common.js` syncs Chart.js on theme change. For **custom colors** (pie segments, badges, etc.):

```javascript
function moduleDarkMode() {
    return document.body.classList.contains('dark-mode');
}

document.addEventListener('primenet:theme-change', () => {
    // Re-read colors and chart.update()
});
```

See `modules/sector_health/static/sector_health.js` (`shPieColors`, `primenet:theme-change` listener).

---

## Header & theme toggle placement

`_ensureThemeToggle()` mounts `#dark-mode-btn` into the first match:

1. `header .header-actions`
2. `header .header-right`
3. `.map-header .header-right`
4. `.ch-topbar .ch-topbar-actions`
5. `.son-topbar .son-topbar-actions`
6. `.nh-header .nh-header-right`
7. `.nh-select-header`

**If dark mode toggle is missing**, ensure the template has one of these containers and loads `common.js`.

Module pages should use the standard header pattern from `common.css` (`header` → `.header-content` → `.header-right`).

---

## Constellation / dashboard special case

- Dashboard map deck (`.constellation-deck`) is **always dark** — it is not tied to `body.dark-mode`
- `body.has-constellation-bg` makes page background transparent so the canvas shows through
- Dashboard cards/tabs have additional rules in `static/css/dashboard.css` under `body.dark-mode`

Do not copy constellation colors into normal module pages.

---

## Checklist — new module page

- [ ] Loads `common.css` then module CSS
- [ ] Loads `common.js` (theme + nav + logout helpers)
- [ ] Uses standard `header` / `.main-content` / `.panel` structure where possible
- [ ] No hardcoded light-only `#fff` surfaces without `body.dark-mode` overrides
- [ ] Form controls inherit dark styles or use `--dm-input` tokens
- [ ] Tables use `.table-wrap` or explicit dark `th`/`td` rules
- [ ] Chart/canvas modules listen for `primenet:theme-change`
- [ ] Tested in **light** and **dark** (toggle in header)
- [ ] Cache-bust query string bumped on changed CSS/JS only

---

## Checklist — fixing a broken dark module

1. Open the page, enable **Dark Mode**, note elements that stay white or unreadable.
2. In DevTools, check whether `body` has class `dark-mode`.
3. Find the rule setting the light color (often module CSS, not `common.css`).
4. Fix using one of:
   - Switch hardcoded colors to `var(--dm-*)` tokens
   - Add `body.dark-mode .your-class { ... }` overrides
   - Rename wrapper to `.panel` / `.section` if it fits the global allowlist
5. If the module introduces a **new panel class name**, either:
   - Add it to the allowlist in `common.css` (`body.dark-mode .your-panel { ... }` block ~line 615), **or**
   - Define dark rules in the module CSS file
6. Re-test toggling light ↔ dark without refresh; charts should update via `common.js`.

---

## Reference implementations

| Module | Dark mode approach |
|--------|-------------------|
| **RET Management** | Explicit `body.dark-mode` block in module CSS — thorough per-component overrides |
| **Sector Health** | CSS variables (partial) + scoped `body.dark-mode.sector-health-page` overrides + Chart.js listener |
| **Network Health** | `:root` `--pn-*` tokens (light only today — needs `body.dark-mode` token overrides) |
| **Reports / Admin** | Mostly standard `.section`, `.report-card` from `common.css` allowlist |
| **Power BI** | `:root` module tokens + `body.dark-mode.pbi-page` overrides (`modules/power_bi/static/power_bi.css`) |
| **Performance** | Large `common.css` coverage for `.hw-toolbar`, `.kpi-chart-card`, etc. |

**Good target:** RET Management style (explicit dark section at bottom of module CSS) **or** token override on `body.dark-mode` (less duplication).

---

## Common failure modes

| Symptom | Likely cause |
|---------|----------------|
| Toggle missing | `common.js` not loaded or no header mount point |
| Theme resets on navigation | Page does not load `common.js`; theme only set on dashboard |
| White cards in dark mode | Module CSS `background: #fff` without dark override |
| Unreadable gray text | Light-mode muted color (`#7f8c8d`) on dark background |
| Inputs stay white | Custom input class not covered by `common.css` |
| Charts wrong after toggle | Module does not listen to `primenet:theme-change` |
| Double toggle / wrong label | Module added its own theme button |

---

## Files to touch (summary)

| File | When |
|------|------|
| `static/css/common.css` | Global tokens, new shared panel class names, header/button/table baselines |
| `static/js/common.js` | Theme engine only (avoid per-module hacks here) |
| `modules/<module>/static/*.css` | Module-specific dark fixes (primary work) |
| `modules/<module>/templates/*.html` | Load order, `body` page class, header structure |
| `static/css/dashboard.css` | Dashboard-only dark rules |
| `static/css/constellation.css` | Radar deck (always dark) |
| `static/css/radio_modules.css` | Shared radio module shell dark rules |

---

## Quick audit command

Find hardcoded light surfaces in module CSS (candidates for dark fixes):

```bash
rg "background:\s*(#fff|#ffffff|white)" modules/*/static/*.css
rg "color:\s*#2c3e50" modules/*/static/*.css
```

Find modules that may ship without theme support:

```bash
rg -L "dark-mode" modules/*/static/*.css
```

---

*Last updated: 2026-07-22 — mandatory module checklist; Power BI token pattern added.*
