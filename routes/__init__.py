"""
Routes package for Nokia Configuration Manager
Contains all modular route blueprints
"""

from .auth_routes import auth_bp
from .xml_parser_routes import xml_parser_bp

__all__ = ['auth_bp', 'xml_parser_bp']
