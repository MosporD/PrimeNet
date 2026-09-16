"""Marketing Portal views."""

from .blueprint import marketing_bp

# Importing the modules attaches their routes to the blueprint.
from . import audit_views, campaigns, catalog, consent, home, segments  # noqa: E402,F401

__all__ = ["marketing_bp"]
