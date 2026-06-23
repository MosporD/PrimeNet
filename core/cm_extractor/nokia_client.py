"""
Nokia MantaRay NM CM Data Repository REST API client.

Based on Nokia CM Open API Web Services (MantaRay NM 24R3-NM):
  Base path: /netact/cm/open-api/persistency/v1
  Auth: HTTP Basic
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

from core.cm_extractor.http_util import format_connection_error, request_json


class NokiaCmError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class NokiaCmClient:
    BASE_PATH = '/netact/cm/open-api/persistency/v1'

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
        mo_batch_size: int = 150,
        batch_delay_sec: float = 0.4,
        max_retries: int = 8,
        retry_base_delay_sec: float = 2.0,
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
        self.mo_batch_size = max(1, mo_batch_size)
        self.batch_delay_sec = max(0.0, batch_delay_sec)
        self.max_retries = max(0, max_retries)
        self.retry_base_delay_sec = max(0.1, retry_base_delay_sec)

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + '/', path.lstrip('/'))

    def _error_message(self, status: int, payload: Any) -> str:
        message = f'Nokia CM API error ({status})'
        if status == 401:
            return (
                'NetAct rejected the CM API credentials (401 Unauthorized). '
                'Check NOKIA_CM_USER and NOKIA_CM_PASSWORD in .env — they must be a '
                'NetAct account with CM Open API access (HTTP Basic), not only a web SSO login. '
                f'Host: {self.base_url}'
            )
        if status == 429:
            return (
                'NetAct rate-limited the CM API (429 Too Many Requests). '
                'Large full-MO exports issue many requests — wait a minute and retry, '
                'or export fewer parameters / MO classes. '
                'You can slow requests via NOKIA_CM_BATCH_DELAY_SEC in .env.'
            )
        if isinstance(payload, dict):
            err = payload.get('error') or {}
            detail = err.get('userMessage') or err.get('developerMessage')
            if detail:
                return f'{message}: {detail}'
        return message

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        query: str = '',
    ) -> Any:
        url = self._url(path)
        if query:
            url = f'{url}?{query.lstrip("?")}'

        delay = self.retry_base_delay_sec
        last_status: int | None = None
        last_payload: Any = None

        for attempt in range(self.max_retries + 1):
            try:
                status, payload = request_json(
                    method,
                    url,
                    headers=headers,
                    body=body,
                    auth=(self.username, self.password),
                    timeout=self.timeout,
                    verify_ssl=self.verify_ssl,
                )
            except ConnectionError as exc:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue
                raise NokiaCmError(
                    format_connection_error(exc, host=self.base_url),
                ) from exc

            last_status = status
            last_payload = payload

            if status == 204:
                return None
            if 200 <= status < 300:
                return payload
            if status in (429, 503) and attempt < self.max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            break

        raise NokiaCmError(
            self._error_message(last_status or 0, last_payload),
            status=last_status,
            payload=last_payload,
        )

    def test_connection(self) -> dict[str, Any]:
        return self._request('GET', 'configuration', query='type=ACTUAL&confId=1')

    def get_mo_classes(self, adapt_ids: list[str] | None = None) -> dict[str, Any]:
        query = ''
        if adapt_ids:
            query = '&'.join(f'adaptId={aid}' for aid in adapt_ids)
        return self._request('GET', 'meta/classes', query=query)

    def query(
        self,
        mo_path: str,
        expressions: list[str],
        *,
        conf_id: int = 1,
        variables: dict[str, str] | None = None,
    ) -> list[list[Any]]:
        body: dict[str, Any] = {
            'confId': conf_id,
            'moPath': mo_path,
            'expressions': expressions,
        }
        if variables:
            body['variables'] = variables
        payload = self._request(
            'POST',
            'query',
            body=body,
            headers={'Content-Type': 'application/json'},
        )
        if isinstance(payload, dict):
            return payload.get('result') or []
        return []

    def query_mo_lites(
        self,
        mo_path: str,
        *,
        conf_id: int = 1,
        variables: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            'confId': conf_id,
            'moPath': mo_path,
        }
        if variables:
            body['variables'] = variables
        payload = self._request(
            'POST',
            'queryMOLites',
            body=body,
            headers={'Content-Type': 'application/json'},
        )
        if isinstance(payload, dict):
            return payload.get('result') or []
        return []

    def get_meta_parameters(
        self,
        mo_classes: list[dict[str, str]],
        *,
        fragments: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {'moClasses': mo_classes}
        if fragments is not None:
            body['fragments'] = fragments
        return self._request(
            'POST',
            'meta/parameters',
            body=body,
            headers={'Content-Type': 'application/json'},
        )

    def get_managed_objects(
        self,
        mo_ids: list[str],
        *,
        conf_id: int = 1,
        batch_size: int | None = None,
    ) -> list[dict[str, Any]]:
        if not mo_ids:
            return []

        chunk_size = max(1, batch_size or self.mo_batch_size)
        all_objects: list[dict[str, Any]] = []

        for batch_index, start in enumerate(range(0, len(mo_ids), chunk_size)):
            if batch_index > 0 and self.batch_delay_sec > 0:
                time.sleep(self.batch_delay_sec)
            chunk = mo_ids[start:start + chunk_size]
            payload = self._request(
                'POST',
                'getManagedObjects',
                body={'confId': conf_id, 'moIds': chunk},
                headers={'Content-Type': 'application/json'},
            )
            if isinstance(payload, dict):
                all_objects.extend(payload.get('managedObjects') or [])

        return all_objects
