"""Parameter dictionary knowledge retrieval for AI assistant (Nokia + Huawei)."""

from __future__ import annotations

import html as html_lib
import os
import re
from typing import Any

try:
    from .nokia_loader import search_nokia_entries as search_nokia
    NOKIA_AVAILABLE = True
except ImportError:
    NOKIA_AVAILABLE = False
    def search_nokia(query: str, limit: int = 15) -> list[dict[str, Any]]:
        return []

HUAWEI_PARAMS_DIR = os.path.join(os.path.dirname(__file__), "huawei_params")
_huawei_toc_cache: list[dict] | None = None

_HUAWEI_FIELD_LABELS = (
    "MO",
    "Parameter ID",
    "Parameter Name",
    "Meaning",
    "Feature ID/Feature Name",
    "MML Command",
    "Value Type",
    "Default Value",
)


_STOP_WORDS = frozenset({
    "what", "does", "do", "the", "a", "an", "is", "are", "was", "were", "be",
    "which", "who", "where", "when", "why", "how", "related", "parameters",
    "parameter", "feature", "features", "about", "explain", "tell", "me",
    "for", "and", "or", "to", "of", "in", "on", "with", "from", "that", "this",
})


def _query_words(query: str) -> list[str]:
    words = [w for w in re.split(r"\W+", (query or "").lower()) if len(w) >= 2]
    filtered = [w for w in words if w not in _STOP_WORDS]
    return filtered or words


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _score_normalized(text: str, words: list[str]) -> int:
    normalized = _normalize_for_match(text)
    if not normalized or not words:
        return 0
    score = 0
    for word in words:
        norm_word = _normalize_for_match(word)
        if not norm_word:
            continue
        if norm_word in normalized:
            score += 4
        elif any(norm_word in part for part in re.findall(r"[a-z0-9]+", normalized)):
            score += 1
    return score


def _merge_vendor_sources(
    nokia: list[dict[str, Any]],
    huawei: list[dict[str, Any]],
    nokia_limit: int = 8,
    huawei_limit: int = 8,
) -> list[dict[str, Any]]:
    """Interleave Nokia and Huawei hits so both vendors appear in answers."""
    nokia = nokia[:nokia_limit]
    huawei = huawei[:huawei_limit]
    merged: list[dict[str, Any]] = []
    for index in range(max(len(nokia), len(huawei))):
        if index < len(nokia):
            merged.append(nokia[index])
        if index < len(huawei):
            merged.append(huawei[index])
    return merged


def parse_huawei_toc() -> list[dict]:
    """Parse the CHM table of contents (.hhc) into a flat list of {name, url}."""
    global _huawei_toc_cache
    if _huawei_toc_cache is not None:
        return _huawei_toc_cache
    hhc_path = os.path.join(HUAWEI_PARAMS_DIR, "mbts-parameter-reference.hhc")
    if not os.path.isfile(hhc_path):
        _huawei_toc_cache = []
        return _huawei_toc_cache
    with open(hhc_path, "r", encoding="gb2312", errors="replace") as f:
        content = f.read()
    entries = re.findall(
        r'<param\s+name="Name"\s+value="([^"]*)"[^>]*>.*?<param\s+name="Local"\s+value="([^"]*)"',
        content,
        re.IGNORECASE | re.DOTALL,
    )
    _huawei_toc_cache = [
        {"name": html_lib.unescape(name), "url": url}
        for name, url in entries
        if name.strip() and url.strip()
    ]
    return _huawei_toc_cache


def _score_text(text: str, words: list[str]) -> int:
    if not words:
        return 0
    lower = (text or "").lower()
    score = 0
    for word in words:
        if word in lower:
            score += 3
        elif any(word in part for part in lower.split()):
            score += 1
    return score


def _truncate(text: str, limit: int = 480) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _extract_huawei_html_fields(filepath: str) -> dict[str, str]:
    full = os.path.join(HUAWEI_PARAMS_DIR, filepath)
    if not os.path.isfile(full):
        return {}
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return {}

    fields: dict[str, str] = {}
    title_match = re.search(r"<title>([^<]+)</title>", content, re.IGNORECASE)
    if title_match:
        fields["title"] = html_lib.unescape(title_match.group(1).strip())

    for label in _HUAWEI_FIELD_LABELS:
        pattern = (
            rf"<th[^>]*>\s*{re.escape(label)}\s*</th>\s*"
            r"<td[^>]*>(.*?)</td>"
        )
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        raw = re.sub(r"<[^>]+>", " ", match.group(1))
        value = html_lib.unescape(re.sub(r"\s+", " ", raw).strip())
        if value:
            fields[label] = _truncate(value, 520 if label == "Meaning" else 240)

    fields["url"] = filepath
    return fields


def search_huawei(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Huawei TOC and enrich top hits with page content."""
    words = _query_words(query)
    if not words:
        return []

    toc = parse_huawei_toc()
    scored: list[tuple[int, dict]] = []
    query_lower = query.lower().strip()

    for entry in toc:
        name = entry.get("name") or ""
        url = entry.get("url") or ""
        score = (
            _score_text(name, words) * 3
            + _score_text(url, words) * 2
            + _score_normalized(name, words) * 4
            + _score_normalized(url, words) * 3
        )
        if query_lower in name.lower():
            score += 10
        if _normalize_for_match(query_lower) and _normalize_for_match(query_lower) in _normalize_for_match(name + url):
            score += 12
        if score <= 0:
            continue
        scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for _, entry in scored[:limit]:
        fields = _extract_huawei_html_fields(entry["url"])
        results.append({
            "vendor": "huawei",
            "type": "reference",
            "name": entry.get("name") or fields.get("title") or entry.get("url"),
            "url": entry.get("url"),
            "mo": fields.get("MO"),
            "parameter_id": fields.get("Parameter ID"),
            "parameter_name": fields.get("Parameter Name"),
            "meaning": fields.get("Meaning"),
            "feature": fields.get("Feature ID/Feature Name"),
            "mml": fields.get("MML Command"),
        })
    return results


def _format_source_for_context(source: dict[str, Any]) -> str:
    if source.get("vendor") == "nokia":
        if source.get("type") == "mo":
            lines = [
                f"Nokia MO: {source.get('mo')}",
                f"Category: {source.get('category')}",
                f"Description: {source.get('description')}",
            ]
            params = source.get("parameters") or []
            if params:
                lines.append("Parameters:")
                for p in params:
                    lines.append(f"  - {p.get('name')}: {p.get('description')}")
                extra = int(source.get("parameter_count") or 0) - len(params)
                if extra > 0:
                    lines.append(f"  ... and {extra} more parameters on this MO")
            return "\n".join(lines)

        lines = [
            f"Nokia parameter: {source.get('parameter')}",
            f"Description: {source.get('description')}",
        ]
        mo_list = source.get("mo_list") or []
        if mo_list:
            lines.append(f"Used on MOs: {', '.join(mo_list)}")
        return "\n".join(lines)

    lines = [f"Huawei reference: {source.get('name')}"]
    for key, label in (
        ("mo", "MO"),
        ("parameter_id", "Parameter ID"),
        ("parameter_name", "Parameter Name"),
        ("meaning", "Meaning"),
        ("feature", "Feature"),
        ("mml", "MML"),
    ):
        value = source.get(key)
        if value and value not in ("None", "-"):
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def build_context(query: str, vendor: str = "all") -> tuple[str, list[dict[str, Any]]]:
    """Return formatted context string and structured source list."""
    vendor = (vendor or "all").lower()
    sources: list[dict[str, Any]] = []

    if vendor == "all":
        sources = _merge_vendor_sources(
            search_nokia(query, limit=10),
            search_huawei(query, limit=10),
            nokia_limit=8,
            huawei_limit=8,
        )
    elif vendor == "nokia":
        sources = search_nokia(query, limit=12)
    else:
        sources = search_huawei(query, limit=12)

    if not sources:
        return "", []

    context_parts: list[str] = []
    max_context = 12000
    per_vendor_budget = 5500 if vendor == "all" else max_context
    vendor_used = {"nokia": 0, "huawei": 0}

    for src in sources:
        block = _format_source_for_context(src)
        src_vendor = src.get("vendor") or "nokia"
        if vendor == "all" and vendor_used.get(src_vendor, 0) + len(block) > per_vendor_budget:
            continue
        context_parts.append(block)
        if vendor == "all":
            vendor_used[src_vendor] = vendor_used.get(src_vendor, 0) + len(block)

    context = "\n\n---\n\n".join(context_parts)
    if len(context) > max_context:
        context = context[: max_context - 3] + "..."
    return context, sources
