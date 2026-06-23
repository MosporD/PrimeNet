"""Read Huawei HedEx (.hdx) documentation archives."""

import mimetypes
import os
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache

HDX_DIR = os.path.join(os.path.dirname(__file__), "docs")

TECH_FILES = {
    "2g": {"file": "2g.hdx", "label": "2G — GBSS22.1"},
    "3g": {"file": "3g.hdx", "label": "3G — RAN22.1"},
    "4g": {"file": "4g.hdx", "label": "4G — eRAN16.1"},
    "5g": {"file": "5g.hdx", "label": "5G — RAN10.1 TDD"},
}

_zips: dict[str, zipfile.ZipFile] = {}


def _hdx_path(tech: str) -> str:
    return os.path.join(HDX_DIR, TECH_FILES[tech]["file"])


def _get_zip(tech: str) -> zipfile.ZipFile:
    if tech not in _zips:
        _zips[tech] = zipfile.ZipFile(_hdx_path(tech), "r")
    return _zips[tech]


@lru_cache(maxsize=4)
def _path_index(tech: str) -> dict[str, str]:
    return {name.lower(): name for name in _get_zip(tech).namelist()}


@lru_cache(maxsize=4)
def get_home_page(tech: str) -> str | None:
    z = _get_zip(tech)
    root = ET.fromstring(z.read("profile.xml"))
    home = (root.findtext("homePage") or "").strip()
    return home or None


def _safe_path(filepath: str) -> str | None:
    filepath = filepath.replace("\\", "/").lstrip("/")
    parts: list[str] = []
    for part in filepath.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    return "/".join(parts) if parts else None


def resolve_path(tech: str, filepath: str) -> str | None:
    safe = _safe_path(filepath)
    if not safe:
        return None
    return _path_index(tech).get(safe.lower())


def read_file(tech: str, filepath: str) -> bytes | None:
    resolved = resolve_path(tech, filepath)
    if not resolved:
        return None
    try:
        return _get_zip(tech).read(resolved)
    except KeyError:
        return None


def guess_mimetype(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    overrides = {
        ".html": "text/html",
        ".htm": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".xml": "application/xml",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }
    if ext in overrides:
        return overrides[ext]
    guessed, _ = mimetypes.guess_type(filepath)
    return guessed or "application/octet-stream"
