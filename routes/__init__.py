"""
Routes package — shared infrastructure blueprints only.
Feature modules have moved to their own top-level directories.
"""

from .auth_routes import auth_bp

__all__ = ['auth_bp']
