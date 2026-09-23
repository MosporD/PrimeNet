"""PrimeNet HTTP implementation of ``NetworkFootprintProvider``.

Configured by ``NEXUS_PRIMENET_API_URL`` + ``NEXUS_PORTAL_API_TOKEN``
(or ``NEXUS_PRIMENET_API_TOKEN``). Never opens PrimeNet database files.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .providers import NetworkFootprintProvider, ProviderResult


def _base_url() -> str:
    return (os.getenv("NEXUS_PRIMENET_API_URL") or "").strip().rstrip("/")


def _token() -> str:
    return (
        os.getenv("NEXUS_PORTAL_API_TOKEN")
        or os.getenv("NEXUS_PRIMENET_API_TOKEN")
        or ""
    ).strip()


class PrimeNetNetworkFootprint(NetworkFootprintProvider):
    name = "network-footprint"
    requires = "PrimeNet Engineering Portal API endpoint"

    def __init__(self, *, base_url: str | None = None, token: str | None = None, timeout: float = 30.0):
        self._base = (base_url if base_url is not None else _base_url()).rstrip("/")
        self._token = token if token is not None else _token()
        self._timeout = timeout

    def available(self) -> bool:
        return bool(self._base and self._token)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> ProviderResult:
        if not self.available():
            return ProviderResult.unavailable(
                "Set NEXUS_PRIMENET_API_URL and NEXUS_PORTAL_API_TOKEN to connect "
                "network-aware targeting to PrimeNet."
            )
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
        url = f"{self._base}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": "NexPulse-NetworkFootprint/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            return ProviderResult.unavailable(
                f"PrimeNet API HTTP {exc.code}: {detail or exc.reason}"
            )
        except Exception as exc:
            return ProviderResult.unavailable(f"PrimeNet API unreachable: {exc}")

        if not data.get("success", True) and data.get("error"):
            return ProviderResult.unavailable(str(data.get("error")))

        return ProviderResult(
            available=True,
            value=data,
            source="primenet.portal_api",
            as_of=data.get("as_of") or (data.get("technology_footprint") or {}).get("as_of"),
            reason="",
        )

    def technology_footprint(self, region: str | None = None) -> ProviderResult:
        return self._get(
            "/api/portal/network-footprint/technologies",
            {"area": region or ""},
        )

    def congested_sites(self) -> ProviderResult:
        return self._get("/api/portal/network-footprint/congested", {"limit": "100"})

    def serviceability(self, region: str | None = None) -> ProviderResult:
        return self._get(
            "/api/portal/network-footprint/serviceability",
            {"area": region or "", "limit": "200"},
        )

    def footprint_bundle(self, region: str | None = None) -> ProviderResult:
        return self._get(
            "/api/portal/network-footprint",
            {"area": region or "", "congested_limit": "50"},
        )


def try_register_primenet_network_provider() -> bool:
    """Register the HTTP provider when URL + token are present. Returns True if wired."""
    from . import providers

    provider = PrimeNetNetworkFootprint()
    if not provider.available():
        return False
    providers.register("network_footprint", provider)
    return True
