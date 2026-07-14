"""Quick live HTTP test: one MRBTS + LNHOIF full MO (bulk path)."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import Cookie, CookieJar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, '.env'), override=True)

PORT = int(os.getenv('FLASK_PORT', '5000'))
BASE = f'http://127.0.0.1:{PORT}'

PAYLOAD = {
    'vendor': 'nokia',
    'conf_id': 1,
    'scope_level': 'MRBTS',
    'site_ids': ['1201'],
    'selections': [{
        'mo_class_id': 'NOKLTE:LNHOIF',
        'version': 'xL25R2_2503_121',
        'export_mode': 'full',
        'parameters': [],
    }],
}


def _session(jar: CookieJar) -> None:
    from database_enhanced import connect_app, create_session, execute_query

    conn = connect_app()
    try:
        cur = execute_query(
            conn,
            "SELECT id FROM users WHERE username = 'Malek.Mohammad' AND is_active = 1 LIMIT 1",
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError('User not found')
        user_id = row['id'] if isinstance(row, dict) else row[0]
    finally:
        conn.close()

    token = create_session(user_id)
    jar.set_cookie(Cookie(
        version=0, name='session_token', value=token,
        port=None, port_specified=False,
        domain='127.0.0.1', domain_specified=True, domain_initial_dot=False,
        path='/', path_specified=True, secure=False,
        expires=None, discard=True, comment=None, comment_url=None,
        rest={'HttpOnly': None}, rfc2109=False,
    ))


def main() -> int:
    jar = CookieJar()
    _session(jar)
    data = json.dumps(PAYLOAD).encode('utf-8')
    req = urllib.request.Request(
        f'{BASE}/api/cm-extractor/extract',
        data=data,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': BASE,
            'Referer': f'{BASE}/cm-extractor',
        },
    )
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    t0 = time.time()
    try:
        with opener.open(req, timeout=120) as resp:
            body = json.loads(resp.read())
            elapsed = time.time() - t0
            print(f'HTTP {resp.status} in {elapsed:.2f}s')
            print('async:', body.get('async'))
            print('mode:', body.get('extraction_mode'))
            print('rows:', body.get('row_count'))
            print('summary:', (body.get('summary') or '')[:400])
            return 0 if body.get('success') else 1
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        print(f'HTTP {exc.code} in {time.time() - t0:.2f}s')
        print(raw[:500])
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
