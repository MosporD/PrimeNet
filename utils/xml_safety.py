from __future__ import annotations

import os
import xml.etree.ElementTree as ET


def parse_xml_file(path: str):
    """
    Parse XML using hardened parser when available.
    defusedxml safely handles vendor exports that include a DOCTYPE.
    Stdlib fallback rejects DTD/entity declarations to limit XXE risk.
    """
    if not os.path.isfile(path):
        raise ValueError("XML file not found")
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        from defusedxml import ElementTree as DET  # type: ignore

        return DET.fromstring(raw)
    except ImportError:
        pass
    except Exception:
        try:
            return ET.fromstring(raw)
        except Exception:
            raise
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("DTD/entity XML is not allowed")
    return ET.fromstring(raw)
