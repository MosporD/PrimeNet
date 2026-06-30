"""Parse and search Huawei HedEx navigation/content."""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from html.parser import HTMLParser
from threading import Thread
from typing import Any

from .hdx import HDX_DIR, TECH_FILES, get_home_page, read_file


_WORD_RE = re.compile(r"\S+")
_SPACE_RE = re.compile(r"\s+")
_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")


class _HtmlTextExtractor(HTMLParser):
    """Extract searchable text from HedEx HTML without third-party parsers."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return _SPACE_RE.sub(" ", " ".join(self._chunks)).strip()


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


def _decode_document(raw: bytes) -> str:
    for encoding in ("utf-8", "windows-1256", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _document_text(raw: bytes, url: str) -> str:
    decoded = _decode_document(raw)
    if url.lower().endswith((".html", ".htm")):
        parser = _HtmlTextExtractor()
        parser.feed(decoded)
        parser.close()
        return parser.text()
    return _SPACE_RE.sub(" ", decoded).strip()


def _query_words(query: str) -> list[str]:
    return [word.lower() for word in _WORD_RE.findall(query.strip())]


def _snippet(text: str, words: list[str], width: int = 180) -> str:
    if not text:
        return ""

    lower = text.lower()
    positions = [lower.find(word) for word in words if word and lower.find(word) >= 0]
    if not positions:
        return ""

    pos = min(positions)
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def _score(entry: dict[str, Any], words: list[str], phrase: str) -> int | None:
    title = entry["name_lc"]
    path = entry["path_lc"]
    text = entry["text_lc"]
    score = 0

    for word in words:
        if word in title:
            score += 60
        elif word in path:
            score += 40
        elif word in text:
            score += 10
        else:
            return None

    if phrase in title:
        score += 120
    elif phrase in path:
        score += 80
    elif phrase in text:
        score += 25

    return score


def _search_cache_path(tech: str) -> str:
    return os.path.join(_CACHE_DIR, f"{tech}_search_index.json")


def _source_mtime(tech: str) -> float:
    hdx_path = os.path.join(HDX_DIR, TECH_FILES[tech]["file"])
    return os.path.getmtime(hdx_path)


def _load_cached_search_index(tech: str) -> list[dict[str, Any]] | None:
    try:
        with open(_search_cache_path(tech), "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("source_mtime") != _source_mtime(tech):
        return None

    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None
    return entries


def _save_cached_search_index(tech: str, entries: list[dict[str, Any]]) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_search_cache_path(tech), "w", encoding="utf-8") as fh:
            json.dump({"source_mtime": _source_mtime(tech), "entries": entries}, fh)
    except OSError:
        pass


def _with_search_fields(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **entry,
            "name_lc": (entry.get("name") or "").lower(),
            "path_lc": (entry.get("path") or "").lower(),
            "text_lc": (entry.get("text") or "").lower(),
        }
        for entry in entries
    ]


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


@lru_cache(maxsize=4)
def _get_search_index(tech: str) -> list[dict[str, Any]]:
    cached = _load_cached_search_index(tech)
    if cached is not None:
        return _with_search_fields(cached)

    payload = get_navi_payload(tech)
    index: list[dict[str, Any]] = []

    for entry in payload.get("flat", []):
        url = entry.get("url") or ""
        raw = read_file(tech, url) if url else None
        text = _document_text(raw, url) if raw else ""
        name = entry.get("name") or ""
        path = entry.get("path") or name
        index.append({
            "name": name,
            "url": url,
            "path": path,
            "text": text,
        })

    _save_cached_search_index(tech, index)
    return _with_search_fields(index)


def warm_search_index(tech: str) -> None:
    if tech not in TECH_FILES:
        return
    Thread(target=_get_search_index, args=(tech,), daemon=True).start()


def search_docs(tech: str, query: str, limit: int = 100) -> list[dict[str, Any]]:
    words = _query_words(query)
    if not words:
        return []

    phrase = " ".join(words)
    matches: list[tuple[int, dict[str, Any]]] = []
    for entry in _get_search_index(tech):
        score = _score(entry, words, phrase)
        if score is None:
            continue
        matches.append((score, entry))

    matches.sort(key=lambda item: (-item[0], item[1]["path"].lower()))
    results: list[dict[str, Any]] = []
    for score, entry in matches[: max(1, min(limit, 400))]:
        results.append({
            "name": entry["name"],
            "url": entry["url"],
            "path": entry["path"],
            "snippet": _snippet(entry["text"], words),
            "score": score,
        })
    return results
