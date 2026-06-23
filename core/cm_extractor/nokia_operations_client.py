"""
Nokia MantaRay NM CM Operations REST API client.

Base path: /netact/cm/open-api/operations/v1
Used for Import_Export actualExport (full RNC/BSC RAML/XML dumps).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

from core.cm_extractor.http_util import format_connection_error, request_json


class NokiaOperationsError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class NokiaOperationsClient:
    BASE_PATH = '/netact/cm/open-api/operations/v1'
    TERMINAL_STATUSES = frozenset({'FINISHED', 'FAILED', 'INTERRUPTED'})

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        base_url: str = '',
        use_https: bool = True,
        verify_ssl: bool = False,
        timeout: int = 120,
        poll_interval_sec: float = 3.0,
    ):
        base_url = (base_url or '').strip().rstrip('/')
        if base_url:
            self.base_url = base_url if base_url.endswith(self.BASE_PATH) else base_url + self.BASE_PATH
        else:
            host = (host or '').strip().rstrip('/')
            if host.startswith('http://') or host.startswith('https://'):
                self.base_url = host.rstrip('/') + self.BASE_PATH
            else:
                scheme = 'https' if use_https else 'http'
                self.base_url = f'{scheme}://{host}{self.BASE_PATH}'
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.poll_interval_sec = max(1.0, poll_interval_sec)

    def _url(self, path: str, *, query: str = '') -> str:
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        if query:
            return f'{url}?{query.lstrip("?")}'
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: str = '',
        content_type: str = 'application/json',
        accept: str = 'application/json',
    ) -> Any:
        headers = {'Accept': accept}
        if body is not None:
            headers['Content-Type'] = content_type
        try:
            status, payload = request_json(
                method,
                self._url(path, query=query),
                headers=headers,
                body=body,
                auth=(self.username, self.password),
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )
        except ConnectionError as exc:
            raise NokiaOperationsError(
                format_connection_error(exc, host=self.base_url),
            ) from exc

        if 200 <= status < 300:
            return payload
        raise NokiaOperationsError(
            self._error_message(status, payload),
            status=status,
            payload=payload,
        )

    def _error_message(self, status: int, payload: Any) -> str:
        if status == 401:
            return (
                'NetAct rejected CM Operations API credentials (401). '
                'Check NOKIA_CM_USER / NOKIA_CM_PASSWORD and CM Operations permissions.'
            )
        if isinstance(payload, dict):
            err = payload.get('error') or {}
            detail = err.get('userMessage') or err.get('developerMessage')
            if detail:
                return f'CM Operations API error ({status}): {detail}'
        return f'CM Operations API error ({status})'

    def get_definitions(self) -> list[dict[str, Any]]:
        payload = self._request(
            'GET',
            'definitions',
            accept='application/vnd.nokia-operation-definitions-v1+json',
        )
        if isinstance(payload, dict):
            return payload.get('operationDefs') or []
        return []

    def start_operation(
        self,
        operation_name: str,
        *,
        operation_alias: str = '',
        attributes: dict[str, str] | None = None,
    ) -> str:
        body = {
            'operationName': operation_name,
            'operationAlias': operation_alias or operation_name,
            'operationAttributes': attributes or {},
        }
        payload = self._request(
            'POST',
            'start',
            body=body,
            content_type='application/vnd.nokia-operation-start-v1+json',
            accept='application/vnd.nokia-operation-execution-v1+json',
        )
        if not isinstance(payload, dict) or not payload.get('operationId'):
            raise NokiaOperationsError('CM Operations start did not return operationId')
        return str(payload['operationId'])

    def get_statuses(self, operation_ids: list[str]) -> list[dict[str, Any]]:
        if not operation_ids:
            return []
        query = '&'.join(f'operationIds={op_id}' for op_id in operation_ids)
        payload = self._request(
            'GET',
            'statuses',
            query=query,
            accept='application/vnd.nokia-operation-statuses-v1+json',
        )
        if isinstance(payload, dict):
            return payload.get('statuses') or []
        return []

    def get_attributes(self, operation_ids: list[str]) -> list[dict[str, Any]]:
        if not operation_ids:
            return []
        query = '&'.join(f'operationIds={op_id}' for op_id in operation_ids)
        payload = self._request(
            'GET',
            'attributes',
            query=query,
            accept='application/vnd.nokia-operations-attributes-v1+json',
        )
        if isinstance(payload, dict):
            return payload.get('operationAttributes') or []
        return []

    def get_feedbacks(
        self,
        operation_id: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after = ''
        while True:
            query = f'operationIds={operation_id}&limit={limit}'
            if after:
                query += f'&after={after}'
            payload = self._request(
                'GET',
                'feedbacks',
                query=query,
                accept='application/vnd.nokia-operation-feedbacks-v1+json',
            )
            if not isinstance(payload, dict):
                break
            batch = payload.get('feedbacks') or []
            items.extend(batch)
            next_link = payload.get('nextPageLink')
            if not next_link or not batch:
                break
            if 'after=' in str(next_link):
                after = str(next_link).split('after=')[-1].split('&')[0]
            else:
                break
        return items

    def wait_for_operation(
        self,
        operation_id: str,
        *,
        timeout_sec: int = 900,
    ) -> tuple[str, list[dict[str, Any]]]:
        deadline = time.time() + max(30, timeout_sec)
        last_status = 'STARTED'
        while time.time() < deadline:
            statuses = self.get_statuses([operation_id])
            if statuses:
                last_status = str(statuses[0].get('status') or last_status)
                if last_status in self.TERMINAL_STATUSES:
                    feedbacks = self.get_feedbacks(operation_id)
                    return last_status, feedbacks
            time.sleep(self.poll_interval_sec)
        raise NokiaOperationsError(
            f'CM Operations export timed out after {timeout_sec}s (last status: {last_status}).',
        )
