"""Simulate browser CM Extractor HTTP flow (login cookie + extract + poll)."""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, '.')

from app import app
from database_enhanced import connect_app, create_session, execute_query

inv = json.load(open('data/nokia_netact_inventory.json', encoding='utf-8'))
SITE_IDS = [
    s['site_id']
    for s in inv['scopes']['MRBTS']
    if (s.get('area') or '').lower() == 'south jordan'
]

FULL_MO_PAYLOAD = {
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


def _session_cookie() -> str:
    conn = connect_app()
    try:
        cur = execute_query(conn, "SELECT id FROM users WHERE is_active = 1 ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            raise RuntimeError('No active user in database')
        user_id = row['id'] if isinstance(row, dict) else row[0]
    finally:
        conn.close()
    return create_session(user_id)


def run_extract(label: str, payload: dict) -> None:
    print(f'\n=== {label} ===')
    print(f'Sites: {len(payload.get("site_ids") or [])}')
    sel = (payload.get('selections') or [{}])[0]
    print(f'export_mode: {sel.get("export_mode")!r}, params: {len(sel.get("parameters") or [])}')

    token = _session_cookie()
    client = app.test_client()
    auth_headers = {
        'Content-Type': 'application/json',
        'Cookie': f'session_token={token}',
    }
    t0 = time.time()

    response = client.post(
        '/api/cm-extractor/extract',
        json=payload,
        headers=auth_headers,
    )
    data = response.get_json(silent=True) or {}
    t_post = time.time() - t0
    print(f'POST {response.status_code} in {t_post:.2f}s async={data.get("async")}')

    if response.status_code != 200 or not data.get('success'):
        print('FAILED:', data.get('error') or data)
        return

    file_id = data.get('file_id')
    if data.get('async'):
        print('Polling extract-status...')
        while True:
            time.sleep(2)
            status_resp = client.get(
                f'/api/cm-extractor/extract-status/{file_id}',
                headers={'Cookie': f'session_token={token}'},
            )
            status_data = status_resp.get_json(silent=True) or {}
            status = status_data.get('status')
            if status in ('pending', 'running'):
                elapsed = time.time() - t0
                print(f'  ... still {status} ({elapsed:.0f}s)')
                if elapsed > 600:
                    print('TIMEOUT waiting for extract')
                    return
                continue
            if status == 'error':
                print('ERROR:', status_data.get('error'))
                return
            data = status_data
            break

    elapsed = time.time() - t0
    mode = data.get('extraction_mode', '?')
    summary = (data.get('summary') or '')[:400]
    print(f'DONE in {elapsed:.1f}s')
    print(f'extraction_mode: {mode}')
    print(f'rows: {data.get("row_count")}')
    print(f'summary: {summary}')
    bulk = 'Import_Export' in (data.get('summary') or '')
    open_api = 'Open API' in (data.get('summary') or '') or mode == 'selection'
    print('PATH:', 'BULK (Operations)' if bulk else ('OPEN API' if open_api else 'unknown'))


def main() -> int:
    run_extract('Browser-like: Full MO export', FULL_MO_PAYLOAD)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
