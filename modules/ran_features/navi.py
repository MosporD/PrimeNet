"""Parse Huawei HedEx navi.xml into a browsable tree."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any

from .hdx import get_home_page, read_file


def _navi_path(tech: str) -> str:
    return "resources/navi.xml"


def _resolve_doc_url(navi_url: str) -> str | None:
    url = (navi_url or "").strip()
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return None
    if url.startswith("resources/"):
        return url
    return f"resources/{url.lstrip('/')}"


def _parse_topic(node: ET.Element, ancestors: list[str]) -> dict[str, Any] | None:
    name = (node.attrib.get("txt") or "").strip()
    if not name:
        return None

    doc_url = _resolve_doc_url(node.attrib.get("url", ""))
    path_parts = [*ancestors, name]
    children: list[dict[str, Any]] = []
    for child in node:
        if child.tag != "topic":
            continue
        parsed = _parse_topic(child, path_parts)
        if parsed:
            children.append(parsed)

    return {
        "name": name,
        "url": doc_url,
        "path": " › ".join(path_parts),
        "children": children,
    }


def _flatten_tree(nodes: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    for node in nodes:
        if node.get("url"):
            out.append({"name": node["name"], "url": node["url"], "path": node["path"]})
        _flatten_tree(node.get("children") or [], out)


@lru_cache(maxsize=4)
def get_navi_payload(tech: str) -> dict[str, Any]:
    raw = read_file(tech, _navi_path(tech))
    if not raw:
        return {"home": get_home_page(tech), "tree": [], "flat": [], "total": 0}

    root = ET.fromstring(raw)
    tree: list[dict[str, Any]] = []
    for child in root:
        if child.tag != "topic":
            continue
        parsed = _parse_topic(child, [])
        if parsed:
            tree.append(parsed)

    flat: list[dict[str, Any]] = []
    _flatten_tree(tree, flat)
    return {
        "home": get_home_page(tech),
        "tree": tree,
        "flat": flat,
        "total": len(flat),
    }
