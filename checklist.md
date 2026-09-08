# Dashboard & module UI unification

Fixed scope for the current UI refresh effort.

## Definition of done

- [x] All module templates load `common.css` and use consistent PrimeNet header/back-link patterns
- [x] Dashboard uses `constellation.css` + `constellation.js` as the single source of theme tokens
- [x] `radio_module.html` is the shared shell for radio filter modules (no duplicated filter markup)
- [x] Login and register pages match dashboard visual language
- [x] No duplicated inline styles across module templates — prefer shared CSS classes
- [x] Cache-bust query strings bumped only on files actually changed (`?v=X.X`)
- [ ] Verified in browser: dashboard, one radio module, one standalone module (e.g. network health), login/logout flow

## Notes (2026-09-06)

- Auth shell: `static/css/login.css` shared by login / register / activation (NexusCore constellation). Old `auth.css` no longer linked from templates.
- Module pages: missing body page-classes added; SON + Documentation gained Logout; theme toggle mounts on `.doc-header-right`.
- Auth / portal pages intentionally omit `common.css` (avoids the 0.67 UI zoom on full-bleed constellation screens).

## Out of scope

- Backend route or API changes unless required for UI bugs
- `huawei_params/` reference HTML
- Pipeline / ETL scripts
- New features beyond visual consistency
- Pixel-unifying every bespoke topbar (map / heatmap / SON / NH) into one markup — those keep specialized headers but share tokens, back link, logout, and theme toggle
