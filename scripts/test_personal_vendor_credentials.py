"""One-off: verify personal NetAct / U2020 accounts for CM + RET read access."""

from __future__ import annotations

import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, '.env'), override=True)

from core.cm_extractor.config import build_nokia_operations_client, huawei_defaults, nokia_defaults
from core.cm_extractor.extraction import build_huawei_client, build_nokia_client
from core.cm_extractor.huawei_client import HuaweiCmClient, HuaweiCmError
from core.cm_extractor.nokia_client import NokiaCmClient, NokiaCmError
from core.cm_extractor.nokia_operations_client import NokiaOperationsClient, NokiaOperationsError
from core.cm_extractor.site_catalog import list_huawei_db_sites, resolve_huawei_ne_names
from modules.ret_management import logic as ret_logic

NOKIA_SITE = '101'
HUAWEI_SITE = None  # resolved from metadata


def _status(label: str, ok: bool, detail: str = '') -> None:
    mark = 'PASS' if ok else 'FAIL'
    line = f'[{mark}] {label}'
    if detail:
        line += f' — {detail}'
    print(line)


def _truncate(text: str, limit: int = 200) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[: limit - 3] + '...'


def test_nokia(username: str, password: str) -> dict[str, bool]:
    cfg = nokia_defaults()
    results: dict[str, bool] = {}
    print(f'\n=== Nokia NetAct — {username} ===')

    client = NokiaCmClient(
        host=cfg['host'],
        username=username,
        password=password,
        base_url=cfg.get('base_url') or '',
        use_https=cfg['use_https'],
        verify_ssl=cfg['verify_ssl'],
        timeout=min(cfg.get('timeout', 180), 120),
        mo_batch_size=cfg.get('mo_batch_size', 150),
        batch_delay_sec=cfg.get('batch_delay_sec', 0.4),
        max_retries=2,
        retry_base_delay_sec=cfg.get('retry_base_delay_sec', 2.0),
    )

    try:
        payload = client.test_connection()
        conf = payload.get('configuration') if isinstance(payload, dict) else payload
        _status('CM login + configuration', True, f'conf entries: {len(conf or []) if isinstance(conf, list) else "ok"}')
        results['cm_login'] = True
    except NokiaCmError as exc:
        _status('CM login + configuration', False, _truncate(str(exc)))
        results['cm_login'] = False
        return results

    try:
        classes = client.get_mo_classes(['NOKLTE'])
        count = len(classes.get('moClasses') or []) if isinstance(classes, dict) else 0
        _status('CM meta/classes (NOKLTE)', True, f'{count} MO classes')
        results['cm_meta'] = True
    except NokiaCmError as exc:
        _status('CM meta/classes (NOKLTE)', False, _truncate(str(exc)))
        results['cm_meta'] = False

    try:
        rows, warnings, _write_mo = ret_logic.fetch_nokia_retu_angles(
            client, site_id=NOKIA_SITE, conf_id=1,
        )
        tilt_rows = sum(1 for r in rows if r.get('angle') not in (None, '', '32767'))
        _status(
            'RET read (RETU_R)',
            True,
            f'site {NOKIA_SITE}: {len(rows)} RETU rows, {tilt_rows} with angle'
            + (f'; warn: {warnings[0][:80]}' if warnings else ''),
        )
        results['ret_read'] = True
    except (NokiaCmError, ValueError) as exc:
        _status('RET read (RETU_R)', False, _truncate(str(exc)))
        results['ret_read'] = False

    ops = NokiaOperationsClient(
        host=cfg['host'],
        username=username,
        password=password,
        base_url=cfg.get('base_url') or '',
        use_https=cfg['use_https'],
        verify_ssl=cfg['verify_ssl'],
        timeout=min(cfg.get('timeout', 180), 120),
    )
    try:
        defs = ops.get_definitions()
        names = [d.get('operationName') or d.get('name') for d in defs[:5] if isinstance(d, dict)]
        _status('CM Operations API', True, f'{len(defs)} operations; sample: {", ".join(n for n in names if n)[:120]}')
        results['cm_operations'] = True
    except NokiaOperationsError as exc:
        _status('CM Operations API', False, _truncate(str(exc)))
        results['cm_operations'] = False

    return results


def _build_huawei(username: str, password: str) -> HuaweiCmClient:
    cfg = huawei_defaults()
    return build_huawei_client({
        'host': cfg['host'],
        'port': cfg['port'],
        'username': username,
        'password': password,
        'verify_ssl': cfg['verify_ssl'],
        'use_https': cfg['use_https'],
        'api_style': cfg['api_style'],
        'client_ip': cfg.get('client_ip') or '',
        'script_base_url': cfg.get('script_base_url') or '',
    })


def test_huawei(username: str, passwords: list[str]) -> dict[str, bool]:
    cfg = huawei_defaults()
    results: dict[str, bool] = {}
    print(f'\n=== Huawei U2020 — {username} ===')

    client = None
    last_error = ''
    for password in passwords:
        try:
            client = _build_huawei(username, password)
            client.login()
            _status('OAuth login', True, f'host {cfg["host"]}:{cfg["port"]}')
            results['login'] = True
            break
        except HuaweiCmError as exc:
            last_error = str(exc)
    else:
        _status('OAuth login', False, _truncate(last_error))
        results['login'] = False
        return results

    global HUAWEI_SITE
    sites = list_huawei_db_sites('', scope_level='ENODEB', limit=5)
    if not sites:
        _status('Huawei site catalog', False, 'no eNodeB sites in metadata DB')
        results['site_catalog'] = False
        return results
    HUAWEI_SITE = str(sites[0].get('site_id') or '').strip()
    ne_names = resolve_huawei_ne_names(HUAWEI_SITE)
    ne_name = ne_names[0] if ne_names else ''
    if not ne_name:
        _status('Resolve NE name', False, f'no NE for site {HUAWEI_SITE}')
        results['ne_resolve'] = False
        return results
    _status('Resolve NE name', True, f'site {HUAWEI_SITE} -> {ne_name}')
    results['ne_resolve'] = True

    try:
        rows, warnings = ret_logic.fetch_huawei_rets(client, ne_name=ne_name)
        tilt_rows = sum(1 for r in rows if ret_logic._row_has_tilt_values(r))
        _status(
            'RET read (LST RETSUBUNIT)',
            True,
            f'{len(rows)} rows, {tilt_rows} with tilt'
            + (f'; warn: {warnings[0][:80]}' if warnings else ''),
        )
        results['ret_read'] = True
    except HuaweiCmError as exc:
        _status('RET read (LST RETSUBUNIT)', False, _truncate(str(exc)))
        results['ret_read'] = False

    try:
        reports, errors = client.run_mml_reports('LST NE:;', [ne_name])
        ok = not errors and bool(reports)
        detail = f'{len(reports)} report(s)' if ok else '; '.join(errors[:2]) or 'empty response'
        _status('CM MML (LST NE)', ok, detail)
        results['cm_mml'] = ok
    except HuaweiCmError as exc:
        _status('CM MML (LST NE)', False, _truncate(str(exc)))
        results['cm_mml'] = False

    return results


def summarize(name: str, results: dict[str, bool]) -> None:
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    verdict = 'OK — personal account sufficient' if passed == total and total else f'{passed}/{total} checks passed'
    print(f'\n>>> {name}: {verdict}')


def main() -> int:
    nokia_user = 'malekmoh'
    nokia_pass = os.environ.get('TEST_NETACT_PASSWORD', '').strip()
    huawei_user = 'malek.mohammad'
    huawei_passwords = [
        p.strip()
        for p in os.environ.get('TEST_U2020_PASSWORDS', '').split('|')
        if p.strip()
    ]

    if not nokia_pass or not huawei_passwords:
        print('Set TEST_NETACT_PASSWORD and TEST_U2020_PASSWORDS env vars.', file=sys.stderr)
        return 2

    print('Testing personal vendor credentials (read-only CM + RET queries)')
    print(f'NetAct host: {nokia_defaults().get("host")}')
    print(f'U2020 host:  {huawei_defaults().get("host")}:{huawei_defaults().get("port")}')

    nokia_results = test_nokia(nokia_user, nokia_pass)
    huawei_results = test_huawei(huawei_user, huawei_passwords)

    summarize(f'NetAct {nokia_user}', nokia_results)
    summarize(f'U2020 {huawei_user}', huawei_results)

    shared_nokia = nokia_defaults().get('username') or ''
    if shared_nokia.lower() != nokia_user.lower():
        print(f'\n(reference: shared .env account is {shared_nokia})')

    all_ok = all(nokia_results.values()) and all(huawei_results.values())
    return 0 if all_ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
