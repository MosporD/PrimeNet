"""Live HTTP test: login + South Jordan LNHOIF extract (same path as browser)."""

from __future__ import annotations

import json
import os
import sys

# Unbuffered stdout when run from IDE / background shell.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, '.env'), override=True)

PORT = int(os.getenv('FLASK_PORT', '5000'))
BASE = f'http://127.0.0.1:{PORT}'

inv = json.load(open(os.path.join(ROOT, 'data', 'nokia_netact_inventory.json'), encoding='utf-8'))
SITE_IDS = [
    s['site_id']
    for s in inv['scopes']['MRBTS']
    if (s.get('area') or '').lower() == 'south jordan'
]

PAYLOAD = {
    'vendor': 'nokia',
    'conf_id': 1,
    'scope_level': 'MRBTS',
    'site_ids': SITE_IDS,
    'selections': [{
        'mo_class_id': 'NOKLTE:LNHOIF',
        'version': 'xL25R2_2503_121',
        'export_mode': 'full',
        'parameters': [],
    }],
}


def _request(method: str, path: str, body: dict | None, jar: CookieJar) -> tuple[int, dict]:
    data = None
    headers = {
        'Accept': 'application/json',
        'Origin': BASE,
        'Referer': f'{BASE}/cm-extractor',
    }
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(f'{BASE}{path}', data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        with opener.open(req, timeout=7200) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {'error': raw[:300]}
        return exc.code, payload


def login(jar: CookieJar) -> str:
    user = os.getenv('NCM_BOOTSTRAP_ADMIN_USERNAME', 'admin').strip()
    password = os.getenv('NCM_BOOTSTRAP_ADMIN_PASSWORD') or os.getenv('NCM_DEFAULT_USER_PASSWORD', '')
    if password:
        status, data = _request('POST', '/api/login', {'username': user, 'password': password}, jar)
        if status == 200 and data.get('success'):
            print(f'Logged in as {user} (API login)')
            return user

    from database_enhanced import connect_app, create_session, execute_query
    from http.cookiejar import Cookie

    conn = connect_app()
    try:
        cur = execute_query(
            conn,
            """
            SELECT id, username FROM users
            WHERE is_active = 1 AND force_password_change = 0
            ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError('No active user in database')
        user_id = row['id'] if isinstance(row, dict) else row[0]
        username = row['username'] if isinstance(row, dict) else row[1]
    finally:
        conn.close()

    token = create_session(user_id)
    jar.set_cookie(Cookie(
        version=0,
        name='session_token',
        value=token,
        port=None,
        port_specified=False,
        domain='127.0.0.1',
        domain_specified=True,
        domain_initial_dot=False,
        path='/',
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={'HttpOnly': None},
        rfc2109=False,
    ))
    print(f'Session created for {username} (DB token)')
    return username


def main() -> int:
    print(f'Target: {BASE}')
    print(f'South Jordan sites: {len(SITE_IDS)}')
    print('Selection: LNHOIF full MO export')

    jar = CookieJar()
    login(jar)

    t0 = time.time()
    status, data = _request('POST', '/api/cm-extractor/extract', PAYLOAD, jar)
    print(f'POST /extract -> {status} in {time.time() - t0:.2f}s async={data.get("async")}')

    if status != 200 or not data.get('success'):
        print('FAILED:', data)
        return 1

    file_id = data['file_id']
    if data.get('async'):
        print('Async job started — polling status...')
        while True:
            time.sleep(2)
            st_status, st_data = _request('GET', f'/api/cm-extractor/extract-status/{file_id}', None, jar)
            state = st_data.get('status')
            elapsed = time.time() - t0
            if state in ('pending', 'running'):
                print(f'  {state} ({elapsed:.0f}s)')
                if elapsed > 900:
                    print('TIMEOUT')
                    return 1
                continue
            if state == 'error' or not st_data.get('success'):
                print('ERROR:', st_data.get('error') or st_data)
                return 1
            data = st_data
            break

    elapsed = time.time() - t0
    summary = data.get('summary') or ''
    mode = data.get('extraction_mode', '?')
    bulk = 'Import_Export' in summary
    print()
    print('=' * 60)
    print(f'TOTAL TIME: {elapsed:.1f}s')
    print(f'ROWS: {data.get("row_count")}')
    print(f'MODE: {mode}')
    print(f'PATH: {"BULK (CM Operations)" if bulk else "OPEN API (slow)"}')
    print(f'SUMMARY: {summary[:500]}')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
