"""GET smoke test for PrimeNet module pages (Postgres required).

Hits every dashboard nav href as an admin session and fails on HTTP 500.
503/404 on data-heavy APIs are tolerated; 500 is never OK.

Run: ``python scripts/ci_smoke_routes.py``
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must be set before primenet_app import (app.py re-exports it).
os.environ.setdefault('NCM_SKIP_ACTIVATION', '1')
os.environ.setdefault('NCM_BOOTSTRAP_ON_IMPORT', '0')
os.environ.setdefault('NCM_DISABLE_SCHEDULER', '1')
os.environ.setdefault('NCM_ENABLE_ETL', '0')
os.environ.setdefault('FLASK_SECRET_KEY', 'ci-smoke-secret')
os.environ.setdefault(
    'NCM_BOOTSTRAP_ADMIN_PASSWORD',
    os.environ.get('NCM_CI_ADMIN_PASSWORD', 'ci-smoke-admin-pass'),
)
os.environ.setdefault('NCM_BOOTSTRAP_ADMIN_USERNAME', 'ci_smoke_admin')
os.environ.setdefault('NCM_BOOTSTRAP_ADMIN_EMAIL', 'ci-smoke@local.test')

from datetime import datetime

from core.module_access import NAV_SECTIONS, normalize_href
from core.platform.session import cookie_name
from database_enhanced import create_session, create_user, get_db, init_db
from db.runtime import execute_query
from deploy.bootstrap import run_bootstrap


def _collect_routes() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for section in NAV_SECTIONS:
        for link in section.get('links') or []:
            href = (link.get('href') or '').strip()
            if not href or href.startswith('http'):
                continue
            key = normalize_href(href.split('?', 1)[0])
            if key in seen:
                continue
            seen.add(key)
            out.append(href)
    if '/dashboard' not in {normalize_href(h.split('?', 1)[0]) for h in out}:
        out.insert(0, '/dashboard')
    return out


def _ensure_admin() -> tuple[int, str]:
    init_db()
    with get_db() as conn:
        row = execute_query(
            conn,
            "SELECT id FROM users WHERE username = ? AND is_active LIMIT 1",
            (os.environ['NCM_BOOTSTRAP_ADMIN_USERNAME'],),
        ).fetchone()
    if row:
        uid = int(row['id'] if hasattr(row, 'keys') else row[0])
    else:
        ok, info = create_user(
            username=os.environ['NCM_BOOTSTRAP_ADMIN_USERNAME'],
            email=os.environ['NCM_BOOTSTRAP_ADMIN_EMAIL'],
            password=os.environ['NCM_BOOTSTRAP_ADMIN_PASSWORD'],
            full_name='CI Smoke Admin',
            department='CI',
            role='admin',
            allowed_portals=['primenet'],
        )
        if not ok:
            raise RuntimeError(f'create_user failed: {info}')
        uid = int(info)
    with get_db() as conn:
        execute_query(
            conn,
            'UPDATE users SET password_changed_at = ?, force_password_change = FALSE WHERE id = ?',
            (datetime.now(), uid),
        )
        conn.commit()
    return uid, create_session(uid)


def main() -> int:
    if not (os.getenv('NCM_DATABASE_URL') or os.getenv('NCM_APP_DATABASE_URL')):
        print('SKIP: NCM_DATABASE_URL not set (Postgres smoke requires a database URL).')
        return 0

    run_bootstrap(start_scheduler=False)
    _uid, token = _ensure_admin()

    from app import app

    client = app.test_client()
    client.set_cookie(cookie_name(), token)

    routes = _collect_routes()
    failures: list[str] = []
    print(f'smoke routes: {len(routes)}')
    for href in routes:
        resp = client.get(href, follow_redirects=False)
        code = resp.status_code
        if code >= 500:
            failures.append(f'{href} -> {code}')
            print(f'FAIL {href} {code}')
        else:
            print(f'OK   {href} {code}')

    if failures:
        print('\nFAILED (500+):')
        for line in failures:
            print(f'  {line}')
        return 1
    print('\nsmoke OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
