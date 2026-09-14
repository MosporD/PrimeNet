"""Parse Nokia NBI PM filename / DN metadata for warehouse grain keys."""

from __future__ import annotations

import re
from dataclasses import dataclass


# PM202609111231+030072MRBTS_-_1.xml.gz
# PM202609111218+030072RNC.xml.gz
_FILENAME_RE = re.compile(
    r"^PM(?P<ts>\d{12})\+(?P<tz>\d+)"
    r"(?P<ne_type>MRBTS|LNBTS|WBTS|RNC|BSC|NETACT|NRBTS|ENBTS|OMS|OME)"
    r"(?:_-_(?P<shard>\d+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FileMeta:
    ne_type: str = ""
    shard: str = ""
    pm_timestamp: str = ""  # yyyymmddHHMM from filename
    tz_token: str = ""


def parse_filename(name: str) -> FileMeta:
    base = name.split("/")[-1]
    for suffix in (".xml.gz", ".gz", ".xml"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    m = _FILENAME_RE.match(base)
    if not m:
        return FileMeta()
    return FileMeta(
        ne_type=(m.group("ne_type") or "").upper(),
        shard=m.group("shard") or "",
        pm_timestamp=m.group("ts") or "",
        tz_token=m.group("tz") or "",
    )


def mo_class_from_dn(dn: str) -> str:
    """Leaf MO class from DN, e.g. .../NRCELL-101 → NRCELL."""
    leaf = (dn or "").rstrip("/").split("/")[-1]
    if not leaf:
        return ""
    return leaf.split("-", 1)[0].upper()


def site_key_from_dn(dn: str) -> str:
    for token in ("MRBTS-", "LNBTS-", "WBTS-", "ENB-", "RNC-", "BSC-", "HBTS-"):
        if token in dn:
            part = dn.split(token, 1)[1]
            return token + part.split("/")[0]
    parts = dn.split("/")
    return parts[1] if len(parts) > 1 else dn


def controller_key_from_dn(dn: str) -> str:
    for token in ("RNC-", "BSC-", "MRBTS-", "LNBTS-", "WBTS-", "ENB-"):
        if token in dn:
            part = dn.split(token, 1)[1]
            return token + part.split("/")[0]
    return ""


def tech_guess(dn: str, family: str, ne_type: str = "") -> str:
    u = f"{dn} {family} {ne_type}".upper()
    if ne_type == "MRBTS" or "NRBTS" in u or "/NR" in u or "5G" in u:
        # SBTS files mix NR + transport; prefer DN hints
        if "LNCEL" in u or "LNBTS" in u:
            return "4G"
        if "WCEL" in u or "WBTS" in u:
            return "3G"
        if "NRCELL" in u or "NRBTS" in u or family.upper().startswith("N"):
            return "5G"
    if ne_type == "LNBTS" or "LNCEL" in u or "LNBTS" in u or "LTE" in u:
        return "4G"
    if ne_type == "WBTS" or "WCEL" in u or "WBTS" in u or "WCDMA" in u:
        return "3G"
    if ne_type in ("BSC",) or "GSM" in u:
        return "2G"
    if "NR" in u or "5G" in u:
        return "5G"
    if "LTE" in u or "4G" in u:
        return "4G"
    if "3G" in u or "WCDMA" in u:
        return "3G"
    if "2G" in u or "GSM" in u:
        return "2G"
    return ""
