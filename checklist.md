# Dashboard & module UI unification

Fixed scope for the current UI refresh effort.

## Definition of done

- [ ] All module templates load `common.css` and use consistent PrimeNet header/back-link patterns
- [ ] Dashboard uses `constellation.css` + `constellation.js` as the single source of theme tokens
- [ ] `radio_module.html` is the shared shell for radio filter modules (no duplicated filter markup)
- [ ] Login and register pages match dashboard visual language
- [ ] No duplicated inline styles across module templates — prefer shared CSS classes
- [ ] Cache-bust query strings bumped only on files actually changed (`?v=X.X`)
- [ ] Verified in browser: dashboard, one radio module, one standalone module (e.g. network health), login/logout flow

## Out of scope

- Backend route or API changes unless required for UI bugs
- `huawei_params/` reference HTML
- Pipeline / ETL scripts
- New features beyond visual consistency
