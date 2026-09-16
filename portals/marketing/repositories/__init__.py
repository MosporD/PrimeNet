"""Data access for the Marketing Portal domain entities."""

from . import campaigns, catalog, consent, segments  # noqa: F401
from .common import ValidationError  # noqa: F401

__all__ = ["campaigns", "catalog", "consent", "segments", "ValidationError"]
