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

## History

Phase 1 app-DB callers (2026-08-31). Vendor creds module `core/user_vendor_credentials.py`.

## Plans

None parked.

## Watch-outs

Tests often 403 APIs until password rotation is cleared.
