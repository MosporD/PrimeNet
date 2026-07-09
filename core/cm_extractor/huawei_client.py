"""
Huawei U2020 / MAE northbound REST client for CM extraction.

Supports two Open API stacks (set HUAWEI_CM_API_STYLE in .env):

Wireless / RAN (default) — MAE-Access Open API Developer Guide:
  OAuth:  PUT  /api/rest/securityManagement/v1/oauth/token
  MML:    POST /api/rest/mmlManagement/v1/command
  Batch:  POST /api/rest/mmlManagement/v1/tasks (+ status/result/delete)
  Cells:  POST /api/rest/resourceManagement/v1/topocellsinfo

CN U2020 V300R019 — Open API Development Guide (For CN):
  Token:  POST /rest/cnopenapi-sm/v1/tokens
  MML:    POST /rest/cnopenapi-config/v1/mml-script-task (+ GET status)
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from typing import Any

from urllib.parse import urljoin

from core.cm_extractor.http_util import (
    request_bytes,
    request_json,
    request_json_with_headers,
    request_multipart,
)
from core.cm_extractor.mml_parser import normalize_mml_command, parse_mml_report, is_status_only_mml_report

_MML_ERROR_MARKERS = (
    'incorrect command format',
    'permission denied',
    'invalid command',
    'is not exist',
    'is inexecutable',
    'execution failed',
    'not exist',
    'retecode = 1',
    'retcode = 1',
)


class HuaweiCmError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class HuaweiCmClient:
    MML_TASK_COMPLETE = 3

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 31943,
        use_https: bool = True,
        verify_ssl: bool = False,
        timeout: int = 300,
        poll_interval_sec: float = 3.0,
        api_style: str = 'wireless',
        client_ip: str = '',
        script_base_url: str = '',
    ):
        host = (host or '').strip().rstrip('/')
        if host.startswith('http://') or host.startswith('https://'):
            self.base_url = host.rstrip('/')
        else:
            scheme = 'https' if use_https else 'http'
            self.base_url = f'{scheme}://{host}:{port}'
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.poll_interval_sec = max(1.0, poll_interval_sec)
        self.api_style = (api_style or 'wireless').strip().lower()
        if self.api_style not in ('wireless', 'cn'):
            self.api_style = 'wireless'
        self.client_ip = (client_ip or '').strip()
        self.script_base_url = (script_base_url or '').strip().rstrip('/')
        self._token: str | None = None
        self._last_mml_errors: list[str] = []
        self._skipped_mml_nes: list[dict[str, str]] = []

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + '/', path.lstrip('/'))

    def login(self) -> str:
        if self.api_style == 'cn':
            return self._login_cn()
        return self._login_wireless()

    def _login_wireless(self) -> str:
        status, payload = request_json(
            'PUT',
            self._url('/api/rest/securityManagement/v1/oauth/token'),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Accept-Language': 'en-US',
            },
            body={
                'grantType': 'password',
                'userName': self.username,
                'value': self.password,
            },
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )
        if status != 200 or not isinstance(payload, dict):
            message = 'Huawei login failed'
            if status == 404:
                message = (
                    'Huawei Open API OAuth endpoint not found on this host/port. '
                    'Port 31943 is usually the web UI only — set HUAWEI_CM_PORT=31127 '
                    'for the northbound REST API.'
                )
            elif isinstance(payload, str) and payload.lstrip().startswith('<!'):
                message = (
                    'Huawei returned an HTML page instead of the Open API. '
                    'Use HUAWEI_CM_PORT=31127 (not the web SSO port 31943).'
                )
            elif isinstance(payload, dict):
                message = payload.get('retMessage') or payload.get('message') or message
                ret_code = str(payload.get('retCode') or '')
                if ret_code == '94002':
                    message = (
                        f'{message} Unlock the account in U2020 '
                        '(Security → User Management) or wait for the lockout to expire.'
                    )
                elif ret_code == '94001':
                    message = (
                        f'{message} CM Open API requires a Third-party / NBI user '
                        '(not a personal OSS web login). Check HUAWEI_CM_USER and '
                        'HUAWEI_CM_PASSWORD in .env.'
                    )
            raise HuaweiCmError(message, status=status, payload=payload)

        token = payload.get('accessSession') or payload.get('accessToken')
        if not token:
            raise HuaweiCmError('Huawei login succeeded but no token returned', status=status, payload=payload)
        self._token = token
        return token

    def _login_cn(self) -> str:
        status, payload, headers = request_json_with_headers(
            'POST',
            self._url('/rest/cnopenapi-sm/v1/tokens'),
            body={
                'auth': {
                    'identity': {
                        'password': {
                            'user': {
                                'name': self.username,
                                'password': self.password,
                            },
                        },
                        'methods': ['password'],
                    },
                },
            },
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )
        token = headers.get('x-auth-token', '')
        if not token and isinstance(payload, dict):
            err = str(payload.get('error_code') or '')
            desc = str(payload.get('error_desc') or 'CN Open API login failed')
            if err and err != '0':
                raise HuaweiCmError(desc, status=status, payload=payload)
        if status not in (200, 201) or not token:
            message = 'Huawei CN Open API login failed'
            if isinstance(payload, dict):
                message = payload.get('error_desc') or message
            raise HuaweiCmError(message, status=status, payload=payload)
        self._token = token
        return token

    def _auth_headers(self, *, content_type: str = 'application/json; charset=UTF-8') -> dict[str, str]:
        if not self._token:
            self.login()
        headers = {
            'Accept': 'application/json',
            'X-Auth-Token': self._token or '',
        }
        if content_type:
            headers['Content-Type'] = content_type
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        status, payload = request_json(
            method,
            self._url(path),
            headers=self._auth_headers(),
            body=body,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )
        if status == 401 and retry_on_401:
            self._token = None
            status, payload = request_json(
                method,
                self._url(path),
                headers=self._auth_headers(),
                body=body,
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )
        if status != 200:
            message = f'Huawei API error ({status})'
            if isinstance(payload, dict):
                message = payload.get('retMessage') or payload.get('message') or message
            raise HuaweiCmError(message, status=status, payload=payload)
        return payload

    def test_connection(self) -> dict[str, Any]:
        self.login()
        return {'ok': True, 'message': 'Authentication successful'}

    def run_mml(self, command: str, ne_names: list[str]) -> list[dict[str, Any]]:
        if self.api_style == 'cn':
            raise HuaweiCmError(
                'CN U2020 Open API uses MML script tasks (HTTPS script URL + FTP result). '
                'Set HUAWEI_CM_SCRIPT_BASE_URL and use run_cn_mml_script_task(), or set '
                'HUAWEI_CM_API_STYLE=wireless for direct MML commands.',
            )
        if not ne_names:
            raise HuaweiCmError('At least one NE name is required')
        if len(ne_names) > 100:
            raise HuaweiCmError(
                f'MML single-command API supports at most 100 NEs ({len(ne_names)} given). '
                'Use batch MML script mode for larger exports.',
            )

        command = normalize_mml_command(command)
        payload = self._request_json(
            'POST',
            '/api/rest/mmlManagement/v1/command',
            body={'command': command, 'neNames': ne_names},
        )
        rows, errors = self._parse_mml_results(payload)
        self._last_mml_errors = errors
        return rows

    def run_mml_reports(
        self,
        command: str,
        ne_names: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Run MML and return per-NE report text plus default parsed rows."""
        if self.api_style == 'cn':
            raise HuaweiCmError(
                'CN U2020 Open API uses MML script tasks (HTTPS script URL + FTP result). '
                'Set HUAWEI_CM_SCRIPT_BASE_URL and use run_cn_mml_script_task(), or set '
                'HUAWEI_CM_API_STYLE=wireless for direct MML commands.',
            )
        if not ne_names:
            raise HuaweiCmError('At least one NE name is required')
        if len(ne_names) > 100:
            raise HuaweiCmError(
                f'MML single-command API supports at most 100 NEs ({len(ne_names)} given). '
                'Use batch MML script mode for larger exports.',
            )

        command = normalize_mml_command(command)
        payload = self._request_json(
            'POST',
            '/api/rest/mmlManagement/v1/command',
            body={'command': command, 'neNames': ne_names},
        )
        reports: list[dict[str, Any]] = []
        errors: list[str] = []
        for item in payload.get('results') or []:
            ne_name = str(item.get('name') or '').strip()
            report = str(item.get('report') or '')
            result = str(item.get('result') or '')
            if self._is_mml_error_report(report, result=result):
                errors.append(self._format_ne_mml_error(ne_name, report, result=result))
                continue
            rows = parse_mml_report(report)
            reports.append({
                'ne_name': ne_name,
                'report': report,
                'rows': rows,
            })

        top_message = ''
        if isinstance(payload, dict):
            top_message = str(payload.get('retMessage') or '').strip()
        if top_message and self._is_mml_error_report(top_message):
            if top_message not in errors:
                errors.insert(0, top_message)

        self._last_mml_errors = errors
        return reports, errors

    @staticmethod
    def _missing_ne_names_from_errors(errors: list[str]) -> list[str]:
        missing: list[str] = []
        ne_pattern = re.compile(r'\d+-[^,\s;\n]+')
        for err in errors:
            text = str(err or '')
            lower = text.lower()
            if 'not exist' not in lower and 'does not exist' not in lower:
                continue
            for match in ne_pattern.findall(text):
                name = match.strip().strip('.')
                if name:
                    missing.append(name)
        return list(dict.fromkeys(missing))

    def run_mml_chunked(
        self,
        command: str,
        ne_names: list[str],
        *,
        chunk_size: int = 100,
        alternates_by_ne: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run MML against many NEs using repeated single-command calls (≤100 NEs each).

        When U2020 rejects NE names as non-existent, those NEs are skipped and the
        request is retried with the remaining names. Skipped NEs are recorded via
        ``consume_skipped_mml_nes()``.
        """
        del alternates_by_ne  # legacy kwarg — no synthetic name retries
        if not ne_names:
            raise HuaweiCmError('At least one NE name is required')
        chunk_size = max(1, min(int(chunk_size), 100))

        all_rows: list[dict[str, Any]] = []
        all_errors: list[str] = []
        for start in range(0, len(ne_names), chunk_size):
            chunk = ne_names[start:start + chunk_size]
            rows, errors = self._run_mml_chunk_excluding_missing(command, chunk)
            all_rows.extend(rows)
            all_errors.extend(errors)
        self._last_mml_errors = all_errors
        return all_rows

    def _record_skipped_mml_nes(self, ne_names: list[str], *, reason: str) -> None:
        from core.cm_extractor.huawei_discovery import parse_site_id_from_ne_name

        seen = {row.get('NE name') for row in self._skipped_mml_nes}
        for ne_name in ne_names:
            name = str(ne_name or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            self._skipped_mml_nes.append({
                'NE name': name,
                'Site ID': parse_site_id_from_ne_name(name) or '',
                'Reason': reason,
            })

    def _run_mml_chunk_excluding_missing(
        self,
        command: str,
        ne_names: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        pending = list(ne_names)
        original = set(ne_names)
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        skipped_reason = 'Not found in U2020 (name mismatch)'

        while pending:
            batch_rows = self.run_mml(command, pending)
            batch_errors = self.consume_mml_errors()
            missing = self._missing_ne_names_from_errors(batch_errors)
            if not missing:
                rows.extend(batch_rows)
                errors.extend(batch_errors)
                break

            pending_set = set(pending)
            confirmed = [name for name in missing if name in pending_set]
            if not confirmed:
                confirmed = [name for name in missing if name in original]

            if confirmed:
                self._record_skipped_mml_nes(confirmed, reason=skipped_reason)
                pending = [name for name in pending if name not in set(confirmed)]
                if batch_rows:
                    rows.extend(batch_rows)
                if pending:
                    continue
                errors.extend(
                    err for err in batch_errors
                    if 'not exist' not in err.lower() and 'does not exist' not in err.lower()
                )
                break

            rows.extend(batch_rows)
            errors.extend(batch_errors)
            break

        return rows, errors

    def build_mml_script(self, command: str, ne_names: list[str]) -> str:
        """Format one-line MML script: COMMAND:; {NE1,NE2}."""
        cmd = normalize_mml_command(command)
        ne_list = ','.join(str(n).strip() for n in ne_names if str(n).strip())
        return f'{cmd} {{{ne_list}}}\n'

    def create_mml_batch_task(
        self,
        script_text: str,
        *,
        task_name: str = '',
        secret_key: str = '',
    ) -> str:
        if not self._token:
            self.login()
        # Some U2020 builds only accept the script file (retCode 90001 if taskName/secretKey sent).
        fields: dict[str, str] = {}
        if task_name.strip():
            fields['taskName'] = task_name.strip()
        if secret_key.strip():
            fields['secretKey'] = secret_key.strip()

        def _post(form_fields: dict[str, str] | None) -> tuple[int, Any]:
            return request_multipart(
                'POST',
                self._url('/api/rest/mmlManagement/v1/tasks'),
                headers={
                    'Accept': 'application/json',
                    'X-Auth-Token': self._token or '',
                },
                fields=form_fields or None,
                files={
                    'file': ('mml_script.txt', script_text.encode('utf-8'), 'text/plain'),
                },
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )

        status, payload = _post(fields if fields else None)
        if status == 401:
            self.login()
            status, payload = _post(fields if fields else None)

        if (
            status != 200
            and fields
            and isinstance(payload, dict)
            and 'does not exist' in str(payload.get('retMessage') or '').lower()
        ):
            status, payload = _post(None)
            if status == 401:
                self.login()
                status, payload = _post(None)

        if status != 200 or not isinstance(payload, dict):
            message = 'Failed to create MML batch task'
            if isinstance(payload, dict):
                message = payload.get('retMessage') or message
            raise HuaweiCmError(message, status=status, payload=payload)

        task_id = str(payload.get('taskId') or '').strip()
        if not task_id:
            raise HuaweiCmError('MML batch task created but no taskId returned', status=status, payload=payload)
        return task_id

    def get_mml_task_status(self, task_id: str) -> dict[str, Any]:
        payload = self._request_json('GET', f'/api/rest/mmlManagement/v1/tasks/{task_id}/status')
        if not isinstance(payload, dict):
            return {}
        return payload

    def wait_for_mml_task(
        self,
        task_id: str,
        *,
        timeout_sec: int = 1800,
    ) -> dict[str, Any]:
        deadline = time.time() + max(60, timeout_sec)
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_mml_task_status(task_id)
            state = int(last.get('currentState') or last.get('curentState') or -1)
            if state == self.MML_TASK_COMPLETE:
                return last
            time.sleep(self.poll_interval_sec)
        raise HuaweiCmError(
            f'MML batch task {task_id} timed out after {timeout_sec}s (last status: {last}).',
        )

    def download_mml_task_result(self, task_id: str) -> str:
        if not self._token:
            self.login()
        status, raw, content_type = request_bytes(
            'GET',
            self._url(f'/api/rest/mmlManagement/v1/tasks/{task_id}/result'),
            headers={
                'Accept': 'application/json, text/plain, application/octet-stream',
                'X-Auth-Token': self._token or '',
            },
            timeout=max(self.timeout, 600),
            verify_ssl=self.verify_ssl,
        )
        if status == 401:
            self.login()
            status, raw, content_type = request_bytes(
                'GET',
                self._url(f'/api/rest/mmlManagement/v1/tasks/{task_id}/result'),
                headers={
                    'Accept': 'application/json, text/plain, application/octet-stream',
                    'X-Auth-Token': self._token or '',
                },
                timeout=max(self.timeout, 600),
                verify_ssl=self.verify_ssl,
            )

        if status != 200:
            message = f'Failed to download MML task result ({status})'
            try:
                err = raw.decode('utf-8', errors='replace')
                if err.strip().startswith('{'):
                    import json
                    data = json.loads(err)
                    message = data.get('retMessage') or message
            except Exception:
                pass
            raise HuaweiCmError(message, status=status)

        if 'zip' in (content_type or '').lower() or raw[:2] == b'PK':
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                if not names:
                    raise HuaweiCmError('MML task result ZIP is empty')
                return zf.read(names[0]).decode('utf-8', errors='replace')
        return raw.decode('utf-8', errors='replace')

    def delete_mml_task(self, task_id: str) -> None:
        self._request_json('DELETE', f'/api/rest/mmlManagement/v1/tasks/{task_id}')

    def run_mml_batch(
        self,
        command: str,
        ne_names: list[str],
        *,
        task_name: str = '',
        wait_timeout_sec: int = 1800,
        delete_after: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Create batch task, wait, download result, parse rows."""
        script = self.build_mml_script(command, ne_names)
        task_id = self.create_mml_batch_task(script, task_name=task_name)
        try:
            self.wait_for_mml_task(task_id, timeout_sec=wait_timeout_sec)
            result_text = self.download_mml_task_result(task_id)
            rows, errors = self._parse_batch_result_file(result_text)
            self._last_mml_errors = errors
            return task_id, rows
        finally:
            if delete_after:
                try:
                    self.delete_mml_task(task_id)
                except HuaweiCmError:
                    pass

    def create_cn_mml_script_task(
        self,
        script_https_url: str,
        *,
        serial: bool = False,
        stop_when_error: bool = False,
        start_number: int = 1,
    ) -> dict[str, Any]:
        if not self.client_ip:
            raise HuaweiCmError(
                'HUAWEI_CM_CLIENT_IP must be set for CN MML script tasks (your app server IP).',
            )
        payload = self._request_json(
            'POST',
            '/rest/cnopenapi-config/v1/mml-script-task',
            body={
                'mml_script_path': script_https_url,
                'serial': 'true' if serial else 'false',
                'stop_when_error': 'true' if stop_when_error else 'false',
                'start_number': str(start_number),
                'client_ip': self.client_ip,
            },
        )
        if not isinstance(payload, dict):
            raise HuaweiCmError('Unexpected response from CN MML script task create')
        if int(payload.get('error_code') or 0) != 0:
            raise HuaweiCmError(
                payload.get('error_desc') or 'CN MML script task creation failed',
                payload=payload,
            )
        return payload

    def get_cn_mml_script_task_status(self, task_id: str) -> dict[str, Any]:
        payload = self._request_json(
            'GET',
            f'/rest/cnopenapi-config/v1/mml-script-task/{task_id}',
        )
        return payload if isinstance(payload, dict) else {}

    def wait_for_cn_mml_script_task(
        self,
        task_id: str,
        *,
        timeout_sec: int = 1800,
    ) -> dict[str, Any]:
        deadline = time.time() + max(60, timeout_sec)
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_cn_mml_script_task_status(task_id)
            if int(last.get('error_code') or 0) != 0:
                raise HuaweiCmError(
                    last.get('error_desc') or f'CN MML task {task_id} status query failed',
                    payload=last,
                )
            status = str(last.get('status') or '').strip()
            if status.lower() == 'success':
                return last
            if status.lower() == 'failed':
                raise HuaweiCmError(
                    f'CN MML script task {task_id} failed.',
                    payload=last,
                )
            time.sleep(self.poll_interval_sec)
        raise HuaweiCmError(
            f'CN MML script task {task_id} timed out after {timeout_sec}s (last: {last}).',
        )

    def query_topo_cells(self, fdns: list[str]) -> list[dict[str, Any]]:
        if self.api_style == 'cn':
            raise HuaweiCmError('Topology cells API is only available in wireless API style.')
        if not fdns:
            raise HuaweiCmError('At least one FDN is required for topology cell query')
        if len(fdns) > 500:
            raise HuaweiCmError('Topology cell API supports at most 500 FDNs per request')

        payload = self._request_json(
            'POST',
            '/api/rest/resourceManagement/v1/topocellsinfo',
            body={'fdns': fdns},
        )
        if not isinstance(payload, dict):
            return []
        return payload.get('results') or []

    def consume_mml_errors(self) -> list[str]:
        """Return and clear per-NE MML warnings from the last run_mml / run_mml_batch call."""
        errors = list(self._last_mml_errors)
        self._last_mml_errors = []
        return errors

    def clear_skipped_mml_nes(self) -> None:
        self._skipped_mml_nes = []

    def consume_skipped_mml_nes(self) -> list[dict[str, str]]:
        """Return and clear NE names skipped because U2020 rejected them."""
        skipped = list(self._skipped_mml_nes)
        self._skipped_mml_nes = []
        return skipped

    def _is_mml_error_report(self, report: str, *, result: str = '') -> bool:
        text = f'{report} {result}'.strip().lower()
        if not text:
            return False
        return any(marker in text for marker in _MML_ERROR_MARKERS)

    def _format_ne_mml_error(self, ne_name: str, report: str, *, result: str = '') -> str:
        message = report.strip() or result.strip() or 'MML command failed'
        lower = message.lower()
        if 'inexecutable' in lower or 'invalid command' in lower:
            message += (
                ' Use LTE Cell (LST CELL) or eNodeB Function (LST ENODEBFUNCTION) '
                'for BTS3900 sites — not LST ENODEB / LST GNB.'
            )
        elif 'permission denied' in lower:
            message += (
                ' Ask U2020 admin to grant MML rights for this command to your NBI user.'
            )
        elif 'execution failed' in lower:
            message += (
                ' For MOD RETSUBUNIT: confirm your NBI user has write/MOD rights, '
                'the RET is online, and DEVICENO/SUBUNITNO/TILT are valid '
                '(tilt is usually in 0.1° units, e.g. 80 = 8.0°).'
            )
        prefix = f'{ne_name}: ' if ne_name else ''
        return f'{prefix}{message}'

    def _parse_mml_results(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        parsed_rows: list[dict[str, Any]] = []
        errors: list[str] = []

        for item in payload.get('results') or []:
            ne_name = str(item.get('name') or '').strip()
            report = str(item.get('report') or '')
            result = str(item.get('result') or '')
            if self._is_mml_error_report(report, result=result):
                errors.append(self._format_ne_mml_error(ne_name, report, result=result))
                continue

            rows = parse_mml_report(report)
            for row in rows:
                row = dict(row)
                row['NE'] = ne_name
                parsed_rows.append(row)

        top_message = ''
        if isinstance(payload, dict):
            top_message = str(payload.get('retMessage') or '').strip()

        if top_message and self._is_mml_error_report(top_message):
            if top_message not in errors:
                errors.insert(0, top_message)
        if errors and top_message and top_message.lower() not in ' '.join(errors).lower():
            errors = [f'{top_message} — {err}' if not err.startswith(top_message) else err for err in errors]

        if errors and parsed_rows:
            warning_text = '; '.join(errors[:3])
            if len(errors) > 3:
                warning_text += f' …and {len(errors) - 3} more NE(s)'
            for row in parsed_rows:
                row.setdefault('_mml_warnings', warning_text)

        return parsed_rows, errors

    def _parse_batch_result_file(self, text: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse MML batch result file — extract Report sections per NE."""
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        current_ne = ''
        current_report: list[str] = []
        in_report = False

        def flush_report() -> None:
            nonlocal current_ne, current_report, in_report
            if current_ne and current_report:
                report_text = '\n'.join(current_report)
                if self._is_mml_error_report(report_text):
                    errors.append(self._format_ne_mml_error(current_ne, report_text))
                else:
                    parsed = parse_mml_report(report_text)
                    for row in parsed:
                        item = dict(row)
                        item['NE'] = current_ne
                        rows.append(item)
                    if not parsed and report_text.strip() and not is_status_only_mml_report(report_text):
                        rows.append({'NE': current_ne, 'report': report_text.strip()})
            current_report = []
            in_report = False

        for line in text.replace('\r\n', '\n').split('\n'):
            stripped = line.strip()
            if stripped.startswith('NE :') or stripped.startswith('NE:'):
                flush_report()
                current_ne = stripped.split(':', 1)[-1].strip()
                continue
            if stripped.lower().startswith('report :') or stripped.lower().startswith('report:'):
                in_report = True
                continue
            if in_report:
                if stripped.startswith('MML Command') or stripped.startswith('=========='):
                    flush_report()
                    continue
                current_report.append(line)

        flush_report()
        if rows or errors:
            if errors and rows:
                warning_text = '; '.join(errors[:3])
                if len(errors) > 3:
                    warning_text += f' …and {len(errors) - 3} more NE(s)'
                for row in rows:
                    row.setdefault('_mml_warnings', warning_text)
            return rows, errors

        # Fallback: treat whole file as one MML report block
        for row in parse_mml_report(text):
            rows.append(row)
        return rows, errors
