"""Shared HTTP helpers for CM Open API clients."""

from __future__ import annotations

import json
import socket
import ssl
import threading
import urllib.error
import urllib.request
from typing import Any

try:  # Connection pooling / keep-alive for the high-volume JSON path.
    import requests
    from requests.adapters import HTTPAdapter

    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover - fallback to urllib if requests is absent
    requests = None  # type: ignore[assignment]
    HTTPAdapter = None  # type: ignore[assignment]
    _HAS_REQUESTS = False

_SESSION: Any = None
_SESSION_LOCK = threading.Lock()
_INSECURE_WARNING_SILENCED = False


def _get_session() -> Any:
    """Lazily build a process-wide pooled session with HTTP keep-alive."""
    global _SESSION
    if _SESSION is None:
        with _SESSION_LOCK:
            if _SESSION is None:
                session = requests.Session()
                # Stay stateless like the old urllib path: clients manage their
                # own auth (Basic for Nokia, manual cookies for Huawei), so the
                # session must not silently persist Set-Cookie between requests.
                import http.cookiejar

                session.cookies.set_policy(
                    http.cookiejar.DefaultCookiePolicy(allowed_domains=[]),
                )
                # Retries are handled by the CM clients, not the adapter.
                adapter = HTTPAdapter(
                    pool_connections=16,
                    pool_maxsize=32,
                    max_retries=0,
                )
                session.mount('https://', adapter)
                session.mount('http://', adapter)
                _SESSION = session
    return _SESSION


def _silence_insecure_warning() -> None:
    global _INSECURE_WARNING_SILENCED
    if _INSECURE_WARNING_SILENCED:
        return
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # type: ignore[union-attr]
    except Exception:
        pass
    _INSECURE_WARNING_SILENCED = True


def format_connection_error(
    exc: BaseException,
    *,
    host: str = '',
    url: str = '',
    vendor: str = 'CM',
) -> str:
    """Turn low-level socket/URL errors into actionable CM API messages."""
    message = str(exc).strip()
    target = host or url or 'the CM server'
    env_hint = 'NOKIA_CM_HOST' if vendor.lower() == 'nokia' else 'HUAWEI_CM_HOST'
    lowered = message.lower()
    is_timeout = (
        isinstance(exc, (TimeoutError, socket.timeout))
        or '10060' in message
        or 'timed out' in lowered
        or 'timeout' in lowered
    )
    if is_timeout:
        return (
            f'Connection to {target} timed out. '
            f'Check VPN/network access, confirm {env_hint} in .env, and retry.'
        )
    if '10061' in message or 'connection refused' in lowered:
        return (
            f'Connection to {target} was refused. '
            f'Verify {env_hint} and that the API is reachable from this machine.'
        )
    if 'getaddrinfo failed' in lowered or '11001' in message or 'name or service not known' in lowered:
        return (
            f'Cannot resolve host for {target}. '
            f'Check {env_hint} spelling and DNS/VPN.'
        )
    if 'certificate' in lowered or 'ssl' in lowered:
        return (
            f'SSL error connecting to {target}. '
            f'Try {env_hint.replace("_HOST", "_VERIFY_SSL")}=0 in .env for internal certificates.'
        )
    return f'Cannot reach {target}: {message}'


def build_ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, dict[str, Any] | list[Any] | str | None]:
    """
    Issue a JSON request, reusing a pooled keep-alive connection when possible.

    High-volume CM exports issue hundreds of small requests to the same host;
    a shared ``requests.Session`` avoids a fresh TCP + TLS handshake per call.
    Falls back to ``urllib`` if ``requests`` is unavailable. Contract is
    unchanged: returns ``(status, payload)`` and raises ``ConnectionError``.
    """
    if _HAS_REQUESTS:
        return _request_json_pooled(
            method,
            url,
            headers=headers,
            body=body,
            auth=auth,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    return _request_json_urllib(
        method,
        url,
        headers=headers,
        body=body,
        auth=auth,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )


def _request_json_pooled(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, dict[str, Any] | list[Any] | str | None]:
    req_headers = dict(headers or {})
    json_body = None
    if body is not None:
        json_body = body
        req_headers.setdefault('Content-Type', 'application/json')
        req_headers.setdefault('Accept', 'application/json')

    if not verify_ssl:
        _silence_insecure_warning()

    session = _get_session()
    try:
        resp = session.request(
            method.upper(),
            url,
            headers=req_headers,
            json=json_body,
            auth=auth,
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.exceptions.RequestException as exc:  # type: ignore[union-attr]
        cause = exc.__cause__ if isinstance(exc.__cause__, BaseException) else exc
        raise ConnectionError(format_connection_error(cause, url=url)) from exc

    status = resp.status_code
    raw = resp.text
    if not raw:
        return status, None
    try:
        return status, resp.json()
    except ValueError:
        return status, raw


def _request_json_urllib(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, dict[str, Any] | list[Any] | str | None]:
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        req_headers.setdefault('Content-Type', 'application/json')
        req_headers.setdefault('Accept', 'application/json')

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    if auth:
        import base64
        token = base64.b64encode(f'{auth[0]}:{auth[1]}'.encode()).decode('ascii')
        req.add_header('Authorization', f'Basic {token}')

    ctx = build_ssl_context(verify_ssl)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode('utf-8', errors='replace')
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, BaseException):
            detail = format_connection_error(reason, url=url)
        else:
            detail = format_connection_error(Exception(str(reason)), url=url)
        raise ConnectionError(detail) from exc

    if not raw:
        return status, None

    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def request_json_with_headers(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, dict[str, Any] | list[Any] | str | None, dict[str, str]]:
    """Like request_json but also returns response headers (lower-cased keys)."""
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        req_headers.setdefault('Content-Type', 'application/json')
        req_headers.setdefault('Accept', 'application/json')

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    ctx = build_ssl_context(verify_ssl)
    resp_headers: dict[str, str] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode('utf-8', errors='replace')
        if exc.headers:
            resp_headers = {k.lower(): v for k, v in exc.headers.items()}
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, BaseException):
            detail = format_connection_error(reason, url=url, vendor='huawei')
        else:
            detail = format_connection_error(Exception(str(reason)), url=url, vendor='huawei')
        raise ConnectionError(detail) from exc

    if not raw:
        return status, None, resp_headers

    try:
        return status, json.loads(raw), resp_headers
    except json.JSONDecodeError:
        return status, raw, resp_headers


def request_bytes(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, bytes, str]:
    """HTTP request returning raw body bytes and Content-Type header."""
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}), method=method.upper())
    ctx = build_ssl_context(verify_ssl)
    content_type = ''
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            status = resp.status
            content_type = resp.headers.get('Content-Type', '')
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        content_type = exc.headers.get('Content-Type', '') if exc.headers else ''
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, BaseException):
            detail = format_connection_error(reason, url=url, vendor='huawei')
        else:
            detail = format_connection_error(Exception(str(reason)), url=url, vendor='huawei')
        raise ConnectionError(detail) from exc
    return status, raw, content_type


def request_multipart(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    fields: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> tuple[int, dict[str, Any] | list[Any] | str | None]:
    """
    multipart/form-data upload.

    files: {field_name: (filename, content_bytes, content_type)}
    """
    import uuid

    boundary = f'----PrimeNetBoundary{uuid.uuid4().hex}'
    parts: list[bytes] = []

    for name, value in (fields or {}).items():
        parts.append(f'--{boundary}\r\n'.encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f'{value}\r\n'.encode())

    for name, (filename, content, mime) in (files or {}).items():
        parts.append(f'--{boundary}\r\n'.encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
        )
        parts.append(f'Content-Type: {mime}\r\n\r\n'.encode())
        parts.append(content)
        parts.append(b'\r\n')

    parts.append(f'--{boundary}--\r\n'.encode())
    body = b''.join(parts)

    req_headers = dict(headers or {})
    req_headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    status, raw, _ = request_bytes(
        method,
        url,
        headers=req_headers,
        body=body,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode('utf-8', errors='replace'))
    except json.JSONDecodeError:
        return status, raw.decode('utf-8', errors='replace')
