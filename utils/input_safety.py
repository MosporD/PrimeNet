from __future__ import annotations

import re
from typing import Any


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(value: str, max_len: int) -> str:
    text = str(value or "")
    text = _CTRL_RE.sub("", text)
    if len(text) > max_len:
        text = text[:max_len]
    return text.strip()


def is_malformed_text(value: str) -> bool:
    return bool(_CTRL_RE.search(str(value or "")))


def sanitize_json(
    payload: Any,
    *,
    max_depth: int = 8,
    max_items: int = 3000,
    max_key_len: int = 128,
    max_str_len: int = 4096,
    _depth: int = 0,
    _counter: list[int] | None = None,
) -> Any:
    if _counter is None:
        _counter = [0]
    _counter[0] += 1
    if _counter[0] > max_items:
        raise ValueError("JSON payload has too many items")
    if _depth > max_depth:
        raise ValueError("JSON payload nesting is too deep")

    if payload is None:
        return None
    if isinstance(payload, bool | int | float):
        return payload
    if isinstance(payload, str):
        return sanitize_text(payload, max_str_len)
    if isinstance(payload, list):
        return [
            sanitize_json(
                item,
                max_depth=max_depth,
                max_items=max_items,
                max_key_len=max_key_len,
                max_str_len=max_str_len,
                _depth=_depth + 1,
                _counter=_counter,
            )
            for item in payload
        ]
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            key = sanitize_text(k, max_key_len)
            if not key:
                continue
            out[key] = sanitize_json(
                v,
                max_depth=max_depth,
                max_items=max_items,
                max_key_len=max_key_len,
                max_str_len=max_str_len,
                _depth=_depth + 1,
                _counter=_counter,
            )
        return out
    raise ValueError("Unsupported JSON value type")


def sanitize_mapping_values(
    items: list[tuple[str, str]],
    *,
    max_items: int = 300,
    max_key_len: int = 128,
    max_val_len: int = 4096,
) -> dict[str, str]:
    if len(items) > max_items:
        raise ValueError("Too many input parameters")
    out: dict[str, str] = {}
    for raw_key, raw_val in items:
        key = sanitize_text(raw_key, max_key_len)
        val = sanitize_text(raw_val, max_val_len)
        if is_malformed_text(raw_key) or is_malformed_text(raw_val):
            raise ValueError("Malformed input detected")
        if key:
            out[key] = val
    return out
