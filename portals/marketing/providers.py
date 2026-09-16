"""External data providers.

No subscriber, usage, billing, or network data source is connected yet. Every
surface that would show such data reads it through one of the interfaces
below, so connecting a real source later is a provider swap rather than a
rewrite of views and templates.

Until then each provider reports ``available = False`` with a reason, and the
UI renders an explicit "not connected" state. Nothing invents numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderResult:
    """Outcome of a provider call.

    ``available`` False means no source is connected — the caller must render
    an empty/unavailable state rather than treat ``value`` as a real figure.
    """

    available: bool
    value: Any = None
    reason: str = ""
    source: str = ""
    as_of: str | None = None
    detail: dict = field(default_factory=dict)

    @classmethod
    def unavailable(cls, reason: str) -> "ProviderResult":
        return cls(available=False, reason=reason)


class SegmentSizeProvider:
    """Estimates how many subscribers match a segment definition."""

    name = "segment-size"
    requires = "A subscriber/CRM data source"

    def available(self) -> bool:
        return False

    def estimate(self, definition: dict) -> ProviderResult:
        raise NotImplementedError


class CampaignMetricsProvider:
    """Delivery and conversion metrics for a campaign."""

    name = "campaign-metrics"
    requires = "Channel delivery receipts and a conversion/order feed"

    def available(self) -> bool:
        return False

    def funnel(self, campaign_id: int) -> ProviderResult:
        raise NotImplementedError


class NetworkFootprintProvider:
    """Coverage, serviceability, and capacity facts from the Engineering Portal.

    Architecture rule 4: this must call a PrimeNet HTTP API. It must never open
    a PrimeNet database file, even though both run in the same process today.
    """

    name = "network-footprint"
    requires = "PrimeNet Engineering Portal API endpoint"

    def available(self) -> bool:
        return False

    def technology_footprint(self, region: str | None = None) -> ProviderResult:
        raise NotImplementedError

    def congested_sites(self) -> ProviderResult:
        raise NotImplementedError


class _NullSegmentSize(SegmentSizeProvider):
    def estimate(self, definition: dict) -> ProviderResult:
        return ProviderResult.unavailable(
            "No subscriber data source is connected, so segment size cannot be estimated."
        )


class _NullCampaignMetrics(CampaignMetricsProvider):
    def funnel(self, campaign_id: int) -> ProviderResult:
        return ProviderResult.unavailable(
            "No delivery or conversion feed is connected, so campaign results are unavailable."
        )


class _NullNetworkFootprint(NetworkFootprintProvider):
    def technology_footprint(self, region: str | None = None) -> ProviderResult:
        return ProviderResult.unavailable(
            "The Engineering Portal API is not configured, so network footprint is unavailable."
        )

    def congested_sites(self) -> ProviderResult:
        return ProviderResult.unavailable(
            "The Engineering Portal API is not configured, so capacity data is unavailable."
        )


_REGISTRY: dict[str, Any] = {
    "segment_size": _NullSegmentSize(),
    "campaign_metrics": _NullCampaignMetrics(),
    "network_footprint": _NullNetworkFootprint(),
}


def get(kind: str):
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise KeyError(f"Unknown provider: {kind}") from None


def register(kind: str, provider) -> None:
    """Swap in a real implementation (used once ingestion exists)."""
    if kind not in _REGISTRY:
        raise KeyError(f"Unknown provider: {kind}")
    _REGISTRY[kind] = provider


def status() -> list[dict]:
    """Connection status for every provider, for the portal status panel."""
    rows = []
    for kind, provider in _REGISTRY.items():
        rows.append(
            {
                "kind": kind,
                "name": provider.name,
                "available": bool(provider.available()),
                "requires": provider.requires,
                "configured_by": _ENV_HINTS.get(kind, ""),
            }
        )
    return rows


_ENV_HINTS = {
    "segment_size": "NEXUS_MARKETING_SUBSCRIBER_API",
    "campaign_metrics": "NEXUS_MARKETING_DELIVERY_API",
    "network_footprint": "NEXUS_PRIMENET_API_URL",
}


def env_configured(kind: str) -> bool:
    key = _ENV_HINTS.get(kind)
    return bool(key and (os.getenv(key) or "").strip())
