"""Cross-portal HTTP APIs for NexusCore portals (NexPulse, later Support/Sales).

Auth: ``Authorization: Bearer <NEXUS_PORTAL_API_TOKEN>``.
NexPulse must never open PrimeNet SQLite — only these endpoints.
"""

from .routes import portal_api_bp

__all__ = ["portal_api_bp"]
