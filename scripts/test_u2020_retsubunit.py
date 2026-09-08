"""Huawei U2020 RETSUBUNIT-only credential test."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, '.env'), override=True)

from core.cm_extractor.config import huawei_defaults
from core.cm_extractor.extraction import build_huawei_client
from core.cm_extractor.http_util import request_json
from core.cm_extractor.huawei_client import HuaweiCmError
from core.cm_extractor.site_catalog import list_huawei_db_sites, resolve_huawei_ne_names
from modules.ret_management import logic as ret_logic

USER = os.environ.get('TEST_U2020_USER', 'malek.mohammad')
_raw_passwords = [
    os.environ.get('TEST_U2020_PASSWORD_1', ''),
    os.environ.get('TEST_U2020_PASSWORD_2', ''),
]
if not any(p.strip() for p in _raw_passwords):
    _raw_passwords = ['gdIHJqQ$k19zYBm4']
PASSWORDS: list[str] = []
for p in _raw_passwords:
    p = (p or '').strip()
    if p and p not in PASSWORDS:
        PASSWORDS.append(p)


def _oauth_probe(username: str, password: str) -> tuple[int, dict | str | None]:
    cfg = huawei_defaults()
    scheme = 'https' if cfg['use_https'] else 'http'
    url = f'{scheme}://{cfg["host"]}:{cfg["port"]}/api/rest/securityManagement/v1/oauth/token'
    status, payload = request_json(
        'PUT',
        url,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Accept-Language': 'en-US',
        },
        body={'grantType': 'password', 'userName': username, 'value': password},
        timeout=60,
        verify_ssl=cfg['verify_ssl'],
    )
    return status, payload


def main() -> int:
    cfg = huawei_defaults()
    print(f'U2020 host: {cfg["host"]}:{cfg["port"]}')
    print(f'User: {USER}')
    print('Commands: LST RETSUBUNIT only\n')

    client = None
    for i, password in enumerate(PASSWORDS, 1):
        if not password:
            continue
        status, payload = _oauth_probe(USER, password)
        ret_code = payload.get('retCode') if isinstance(payload, dict) else None
        ret_msg = payload.get('retMessage') if isinstance(payload, dict) else None
        print(f'OAuth probe password #{i}: HTTP {status}, retCode={ret_code}, retMessage={ret_msg}')
        if status != 200:
            msg = str(ret_msg or 'login failed').replace('\u2192', '->')
            print(f'[FAIL] login password #{i}: {msg[:200]}')
            if ret_code == '94001':
                print(
                    '       U2020 rejected login (94001). Wrong password or account '
                    'not enabled as Open API / NBI user on port 31127.'
                )
            if 'locked' in msg.lower() or ret_code == '94002':
                print('\nAccount locked — unlock in U2020 before retrying.')
                return 1
            continue
        client = build_huawei_client({'username': USER, 'password': password})
        client.login()
        print(f'[PASS] OAuth login (password #{i})')
        break
    else:
        shared = cfg.get('username') or ''
        if shared:
            s_status, s_payload = _oauth_probe(shared, cfg.get('password') or '')
            s_code = s_payload.get('retCode') if isinstance(s_payload, dict) else None
            print(f'\nReference shared account {shared}: HTTP {s_status}, retCode={s_code}')
        print('\nCannot run RETSUBUNIT tests — Open API login failed for malek.mohammad.')
        return 1

    sites = list_huawei_db_sites('', scope_level='ENODEB', limit=10)
    ne_name = ''
    site_id = ''
    for site in sites:
        sid = str(site.get('site_id') or '').strip()
        names = resolve_huawei_ne_names(sid)
        if names:
            site_id, ne_name = sid, names[0]
            break
    if not ne_name:
        print('[FAIL] could not resolve NE name')
        return 1
    print(f'[INFO] site {site_id} -> NE {ne_name}\n')

    try:
        rows, warnings = ret_logic.fetch_huawei_rets(client, ne_name=ne_name)
    except HuaweiCmError as exc:
        print(f'[FAIL] LST RETSUBUNIT bulk: {str(exc)[:240]}')
        return 1

    tilt = sum(1 for row in rows if ret_logic._row_has_tilt_values(row))
    print(f'[PASS] LST RETSUBUNIT bulk: {len(rows)} rows, {tilt} with tilt')
    for warn in warnings[:3]:
        print(f'       warn: {warn[:180]}')

    if rows:
        device = ret_logic._alias_lookup(rows[0], 'Device No.')
        subunit = ret_logic._alias_lookup(rows[0], 'Subunit No.')
        if device and subunit:
            reports, errors = ret_logic._run_ret_mml(
                client,
                ne_name,
                'LST',
                device_no=device,
                subunit_no=subunit,
            )
            if errors:
                print(
                    f'[FAIL] LST RETSUBUNIT scoped '
                    f'DEVICENO={device},SUBUNITNO={subunit}: {errors[0][:200]}'
                )
                return 1
            scoped = ret_logic._normalize_ret_rows(
                ret_logic._collect_ret_rows_from_reports(reports, ne_name=ne_name)
            )
            print(
                f'[PASS] LST RETSUBUNIT scoped: {len(scoped)} row(s) '
                f'for dev {device} sub {subunit}'
            )
        else:
            print('[SKIP] scoped LST — bulk row missing Device No. / Subunit No.')

    print('\n>>> U2020 malek.mohammad: RETSUBUNIT-only read tests passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
