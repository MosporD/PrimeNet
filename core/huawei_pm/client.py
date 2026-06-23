"""
Huawei MAE / U2020 Performance Management northbound REST client.

Implements MAE-Access Open API section 5.4 (Performance Management APIs):
  5.4.1 POST /api/rest/performanceManagement/v1/measurementResults
  5.4.2 GET  /api/rest/performanceManagement/v1/measurementResults/{taskId}
  5.4.3 DELETE /api/rest/performanceManagement/v1/measurementResults/{taskId}

Authentication reuses the wireless CM OAuth flow (PUT /oauth/token, X-Auth-Token).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode, urljoin

from core.cm_extractor.http_util import request_json
from core.cm_extractor.huawei_client import HuaweiCmClient


class HuaweiPmError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class HuaweiPmClient:
    """MAE PM Open API client — delegates auth to HuaweiCmClient (wireless stack)."""

    TASK_STATUS_COMPLETE = 2

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 31127,
        use_https: bool = True,
        verify_ssl: bool = False,
        timeout: int = 300,
        poll_interval_sec: float = 3.0,
        poll_timeout_sec: int = 900,
        page_limit: int = 5000,
    ):
        self._cm = HuaweiCmClient(
            host=host,
            username=username,
            password=password,
            port=port,
            use_https=use_https,
            verify_ssl=verify_ssl,
            timeout=timeout,
            poll_interval_sec=poll_interval_sec,
            api_style='wireless',
        )
        self.timeout = timeout
        self.poll_interval_sec = max(1.0, poll_interval_sec)
        self.poll_timeout_sec = max(60, poll_timeout_sec)
        self.page_limit = min(5000, max(1, page_limit))

    @property
    def base_url(self) -> str:
        return self._cm.base_url

    @property
    def verify_ssl(self) -> bool:
        return self._cm.verify_ssl

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + '/', path.lstrip('/'))

    def login(self) -> str:
        return self._cm.login()

    def test_connection(self) -> dict[str, Any]:
        self.login()
        return {'ok': True, 'message': 'Huawei PM Open API authentication successful'}

    def _auth_headers(self) -> dict[str, str]:
        return self._cm._auth_headers()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        ok_statuses: tuple[int, ...] = (200,),
        retry_on_401: bool = True,
    ) -> tuple[int, Any]:
        status, payload = request_json(
            method,
            self._url(path),
            headers=self._auth_headers(),
            body=body,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )
        if status == 401 and retry_on_401:
            self._cm._token = None
            status, payload = request_json(
                method,
                self._url(path),
                headers=self._auth_headers(),
                body=body,
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )
        if status not in ok_statuses:
            message = f'Huawei PM API error ({status})'
            if isinstance(payload, dict):
                message = payload.get('retMessage') or payload.get('message') or message
            raise HuaweiPmError(message, status=status, payload=payload)
        return status, payload

    @staticmethod
    def _normalize_condition(condition: dict[str, Any]) -> dict[str, Any]:
        """Accept flat fields or a nested ``condition`` object."""
        if not condition:
            raise HuaweiPmError('Query condition is required')
        if 'condition' in condition and isinstance(condition['condition'], dict):
            body = dict(condition['condition'])
        else:
            body = dict(condition)
        required = ('startTime', 'endTime', 'period', 'counterIds', 'isQueryAllNe')
        missing = [k for k in required if k not in body]
        if missing:
            raise HuaweiPmError(f'Missing required query fields: {", ".join(missing)}')
        if not body.get('neTypeName') and not body.get('ratTypeName'):
            if int(body.get('isQueryAllNe') or 0) == 1:
                raise HuaweiPmError('neTypeName or ratTypeName is required when isQueryAllNe=1')
        counter_ids = body.get('counterIds') or []
        if not counter_ids:
            raise HuaweiPmError('At least one counter ID is required')
        if len(counter_ids) > 150:
            raise HuaweiPmError(f'At most 150 counters per query ({len(counter_ids)} given)')
        body.setdefault('timeFormat', 'timeString')
        return body

    @staticmethod
    def _unwrap_page(payload: Any) -> dict[str, Any]:
        if isinstance(payload, list):
            return payload[0] if payload else {}
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _marker_done(marker: Any) -> bool:
        if marker is None:
            return True
        text = str(marker).strip().lower()
        return not text or text == 'null'

    def create_measurement_query(self, condition: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """
        5.4.1 — Create a performance data query task.

        Returns (http_status, payload). Status 200 may include inline results; 202 means async.
        """
        body = self._normalize_condition(condition)
        status, payload = self._request_json(
            'POST',
            '/api/rest/performanceManagement/v1/measurementResults',
            body=body,
            ok_statuses=(200, 202),
        )
        if not isinstance(payload, dict):
            raise HuaweiPmError('Unexpected response from measurementResults create', status=status)
        return status, payload

    def get_measurement_results(
        self,
        task_id: str,
        *,
        limit: int | None = None,
        marker: str = '',
    ) -> dict[str, Any]:
        """5.4.2 — Fetch one page of async performance results."""
        task_id = str(task_id or '').strip()
        if not task_id:
            raise HuaweiPmError('taskId is required')
        params: dict[str, str] = {'limit': str(limit or self.page_limit)}
        if marker and not self._marker_done(marker):
            params['marker'] = marker
        query = urlencode(params)
        _, payload = self._request_json(
            'GET',
            f'/api/rest/performanceManagement/v1/measurementResults/{task_id}?{query}',
            ok_statuses=(200,),
        )
        return self._unwrap_page(payload)

    def delete_measurement_query(self, task_id: str) -> dict[str, Any]:
        """5.4.3 — Delete a performance result query task."""
        task_id = str(task_id or '').strip()
        if not task_id:
            raise HuaweiPmError('taskId is required')
        _, payload = self._request_json(
            'DELETE',
            f'/api/rest/performanceManagement/v1/measurementResults/{task_id}',
            ok_statuses=(200,),
        )
        return payload if isinstance(payload, dict) else {'taskId': task_id}

    def wait_for_measurement_results(
        self,
        task_id: str,
        *,
        timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        """Poll 5.4.2 until task status is complete (2), paginating with marker."""
        deadline = time.time() + (timeout_sec or self.poll_timeout_sec)
        marker = ''
        collected: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}

        while time.time() < deadline:
            page = self.get_measurement_results(task_id, marker=marker)
            status = int(page.get('status') or -1)
            if status == self.TASK_STATUS_COMPLETE:
                meta = {
                    'taskId': page.get('taskId') or task_id,
                    'retCode': page.get('retCode'),
                    'retMessage': page.get('retMessage'),
                    'period': page.get('period'),
                    'counterIds': page.get('counterIds') or [],
                    'totalSize': page.get('totalSize'),
                }
                rows = page.get('result') or []
                if rows:
                    collected.extend(rows)
                marker = page.get('marker') or ''
                if self._marker_done(marker):
                    break
                continue
            time.sleep(self.poll_interval_sec)

        if not meta and not collected:
            raise HuaweiPmError(
                f'PM query task {task_id} did not complete within '
                f'{timeout_sec or self.poll_timeout_sec}s.',
            )

        return {
            **meta,
            'result': collected,
            'recordCount': len(collected),
        }

    def query_performance_data(
        self,
        condition: dict[str, Any],
        *,
        delete_after: bool = True,
        poll_timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        """
        End-to-end PM query: create task (5.4.1), fetch all pages (5.4.2), delete task (5.4.3).
        """
        http_status, created = self.create_measurement_query(condition)
        task_id = str(created.get('taskId') or '').strip()
        inline_results = created.get('result') or []

        if http_status == 200 and inline_results and self._marker_done(created.get('marker')):
            payload = {
                'mode': 'sync',
                'taskId': task_id or None,
                'retCode': created.get('retCode'),
                'retMessage': created.get('retMessage'),
                'period': created.get('period'),
                'counterIds': created.get('counterIds') or condition.get('counterIds') or [],
                'result': inline_results,
                'recordCount': len(inline_results),
            }
            if delete_after and task_id:
                try:
                    self.delete_measurement_query(task_id)
                except HuaweiPmError:
                    pass
            return payload

        if not task_id:
            ret_msg = str(created.get('retMessage') or 'PM query did not return a taskId')
            raise HuaweiPmError(ret_msg, status=http_status, payload=created)

        try:
            fetched = self.wait_for_measurement_results(
                task_id,
                timeout_sec=poll_timeout_sec or self.poll_timeout_sec,
            )
            fetched['mode'] = 'async'
            return fetched
        finally:
            if delete_after:
                try:
                    self.delete_measurement_query(task_id)
                except HuaweiPmError:
                    pass

    def set_measurement(self, body: dict[str, Any]) -> dict[str, Any]:
        """5.4.4 — Subscribe or cancel counter measurement on NEs."""
        _, payload = self._request_json(
            'POST',
            '/api/rest/performanceManagement/v1/measurement',
            body=body,
            ok_statuses=(200,),
        )
        if not isinstance(payload, dict):
            raise HuaweiPmError('Unexpected response from measurement subscribe')
        return payload

    def get_measurement_task_status(self, task_id: str) -> dict[str, Any]:
        """5.4.5 — Status of a measurement setting task."""
        _, payload = self._request_json(
            'GET',
            f'/api/rest/performanceManagement/v1/measurement/{task_id}',
            ok_statuses=(200,),
        )
        return payload if isinstance(payload, dict) else {}
