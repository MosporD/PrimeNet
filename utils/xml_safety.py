from __future__ import annotations

import os
import xml.etree.ElementTree as ET


def parse_xml_file(path: str):
    """
    Parse XML using hardened parser when available.
    Fallback rejects DTD/entity declarations before stdlib parse.
    """
    if not os.path.isfile(path):
        raise ValueError("XML file not found")
    with open(path, "rb") as fh:
        raw = fh.read()
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("DTD/entity XML is not allowed")
    try:
        from defusedxml import ElementTree as DET  # type: ignore

        return DET.fromstring(raw)
    except Exception:
        return ET.fromstring(raw)
