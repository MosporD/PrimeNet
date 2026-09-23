# User Profile

Self-service profile, password, vendor OSS credentials, photos.

| | |
|---|---|
| Route | `/profile` |
| Module | `modules/user_profile/routes.py` |
| Access | all |
| Version | V1.0 (`profile` in `module_versions`) |

## Purpose

User row + `user_vendor_credentials` + preferences. Password change satisfies `force_password_change`.

## Approach

`connect_app()` / `table_columns` — Postgres-safe. Credentials are per-user for NetAct/U2020; do not log secrets.

## Progress

Dated work log: [`user-profile.progress.md`](user-profile.progress.md). Do not duplicate long history here — update the progress file when this feature changes. Keep **Plans** as the module NEXT.


## Plans

None parked.

## Watch-outs

Tests often 403 APIs until password rotation is cleared.
