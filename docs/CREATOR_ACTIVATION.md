# Creator operator activation (personal password)

PrimeNet can require **your** password before the app or PM databases run. This is separate from NOC user logins (`admin`, etc.).

## One-time setup

1. In `.env`, use **local** mode (comment out or remove `NCM_LICENSE_SERVER_URL`).
2. Do **not** set `NCM_SKIP_ACTIVATION=1` on production servers.
3. Optional: `NCM_ACTIVATION_PERIOD_DAYS=180` (default is **180 days ≈ six months**).
4. Run:

   ```bash
   python scripts/set_activation_password.py
   ```

5. Unlock (web or CLI):

   ```bash
   python scripts/set_activation_password.py --unlock
   ```

   Or open `http://localhost:5000/activation` and enter the same password.

## What gets stored

| File | Purpose |
|------|---------|
| `core/activation_secrets_local.py` | Password hash + signing key (**never commit**) |
| `.ncm_activation_state` | Current unlock expiry (under project or `NCM_DATA_ROOT`) |

Back up `activation_secrets_local.py` in a **personal** password manager or encrypted store. Without it, you can set a new password with the script, but old deployments keep the old hash until overwritten.

## Every six months

When the period expires, the UI redirects to `/activation`. Enter your password again — no code change required.

## Company deployments without your secret file

A clone of the repo **without** `activation_secrets_local.py` must run `set_activation_password.py` themselves, or they cannot unlock. Your password file is not in git (see `.gitignore`).

## Legal note

This control is **technical access** to run the software. It does not replace employment contracts or IP ownership. See a lawyer for rights to the source code itself.
