"""Streaming Nokia PM file parser (3GPP TS 32.435 measCollecFile).

Supports both layouts:
- Classic: ``<measType p="1">ID</measType>`` + ``<r p="1">v</r>``
- Nokia compact: ``<measTypes>ID1 ID2 …</measTypes>`` + ``<measResults>v1 v2 …</measResults>``
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from lxml import etree

from core.pm_plus.file_meta import mo_class_from_dn

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", re.I)


@dataclass
class CounterSample:
    bucket_ts: str  # ISO8601 end of granPeriod (ROP end)
    object_dn: str
    family: str
    counter_id: str
    value: float | None
    vendor: str = "nokia"
    managed_element: str = ""
    gp_seconds: int = 900
    # Grain tags stamped at ingest (filename / worker context)
    ne_type: str = ""
    stream: str = ""
    mo_class: str = ""


@dataclass
class ParseResult:
    samples: list[CounterSample] = field(default_factory=list)
    families: set[str] = field(default_factory=set)
    objects: set[str] = field(default_factory=set)
    counters: set[str] = field(default_factory=set)
    file_begin: str = ""
    managed_element: str = ""
    vendor_name: str = "Nokia"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parse_duration_seconds(text: str) -> int:
    m = _DURATION_RE.fullmatch((text or "").strip())
    if not m:
        return 900
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return max(1, h * 3600 + mi * 60 + s)


def _open_xml_stream(path: Path):
    raw = path.read_bytes()
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        return gzip.open(io.BytesIO(raw), "rb")
    return io.BytesIO(raw)


def _parse_float_token(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text.upper() in ("NIL", "NULL", "NA", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def hour_floor_iso(ts: str) -> str:
    """Floor an ISO timestamp to the hour (UTC Z)."""
    text = (ts or "").strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def iter_samples_from_path(path: Path | str) -> Iterator[CounterSample]:
    """Stream-parse a .gz/.xml PM file and yield counter samples."""
    path = Path(path)
    context = etree.iterparse(
        _open_xml_stream(path),
        events=("start", "end"),
        recover=True,
    )

    # Positioned types: p-index -> counter id (classic layout)
    meas_types_by_p: dict[str, str] = {}
    # Ordered types for compact Nokia layout
    meas_types_ordered: list[str] = []
    family = ""
    bucket_ts = ""
    gp_seconds = 900
    managed_element = ""
    vendor = "nokia"

    for event, elem in context:
        tag = _local(elem.tag)

        if event == "start" and tag == "measInfo":
            meas_types_by_p = {}
            meas_types_ordered = []
            family = (elem.get("measInfoId") or "UNKNOWN").strip() or "UNKNOWN"
            bucket_ts = ""
            gp_seconds = 900
            continue

        if event != "end":
            continue

        if tag == "fileHeader":
            vendor_raw = (elem.get("vendorName") or "Nokia").strip() or "Nokia"
            vendor = "nokia" if "nokia" in vendor_raw.lower() else vendor_raw.lower()
            elem.clear()
            continue

        if tag == "managedElement":
            managed_element = (elem.get("localDn") or elem.get("userLabel") or "").strip()
            elem.clear()
            continue

        if tag == "measType":
            p = elem.get("p") or ""
            name = (elem.text or "").strip()
            if p and name:
                meas_types_by_p[p] = name
            elif name:
                meas_types_ordered.append(name)
            elem.clear()
            continue

        if tag == "measTypes":
            # Compact: space-separated counter ids
            meas_types_ordered = [t for t in (elem.text or "").split() if t]
            elem.clear()
            continue

        if tag == "granPeriod":
            bucket_ts = (elem.get("endTime") or "").strip()
            gp_seconds = _parse_duration_seconds(elem.get("duration") or "PT900S")
            elem.clear()
            continue

        if tag == "measValue":
            obj_dn = (elem.get("measObjLdn") or managed_element or "").strip()
            # Compact child <measResults>…</measResults>
            results_text = ""
            classic_rs: list[tuple[str, str]] = []
            for child in elem:
                ctag = _local(child.tag)
                if ctag == "measResults":
                    results_text = child.text or ""
                elif ctag == "r":
                    classic_rs.append((child.get("p") or "", child.text or ""))

            mo = mo_class_from_dn(obj_dn)
            me = managed_element or (obj_dn.split("/")[0] if obj_dn else "")
            if results_text and meas_types_ordered:
                values = results_text.split()
                for cid, raw in zip(meas_types_ordered, values):
                    yield CounterSample(
                        bucket_ts=bucket_ts,
                        object_dn=obj_dn,
                        family=family or "UNKNOWN",
                        counter_id=cid,
                        value=_parse_float_token(raw),
                        vendor=vendor or "nokia",
                        managed_element=me,
                        gp_seconds=gp_seconds,
                        mo_class=mo,
                    )
            elif classic_rs and meas_types_by_p:
                for p, raw in classic_rs:
                    cid = meas_types_by_p.get(p)
                    if not cid:
                        continue
                    yield CounterSample(
                        bucket_ts=bucket_ts,
                        object_dn=obj_dn,
                        family=family or "UNKNOWN",
                        counter_id=cid,
                        value=_parse_float_token(raw),
                        vendor=vendor or "nokia",
                        managed_element=me,
                        gp_seconds=gp_seconds,
                        mo_class=mo,
                    )

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
            continue

        if tag in ("measInfo", "measData", "fileFooter"):
            elem.clear()


def parse_file(path: Path | str) -> ParseResult:
    result = ParseResult()
    for sample in iter_samples_from_path(path):
        result.samples.append(sample)
        result.families.add(sample.family)
        result.objects.add(sample.object_dn)
        result.counters.add(sample.counter_id)
        if sample.managed_element:
            result.managed_element = sample.managed_element
        if sample.vendor:
            result.vendor_name = sample.vendor
        if sample.bucket_ts and not result.file_begin:
            result.file_begin = sample.bucket_ts
    return result


def fold_samples_to_hour(
    samples: Iterable[CounterSample],
) -> dict[tuple, dict]:
    """Fold ROP samples into hourly running parts (rule applied at write).

    Key = (hour_ts, object_dn, counter_id, gp_seconds, ne_type, stream).
    Stores sum/weight/min/max so AVG/MAX/MIN/SUM can be finished later.
    """
    out: dict[tuple, dict] = {}
    for s in samples:
        if not s.bucket_ts or not s.object_dn or not s.counter_id:
            continue
        hour_ts = hour_floor_iso(s.bucket_ts)
        gp = int(s.gp_seconds or 900)
        ne = (s.ne_type or "").upper()
        stream = s.stream or ""
        key = (hour_ts, s.object_dn, s.counter_id, gp, ne, stream)
        slot = out.get(key)
        if slot is None:
            out[key] = {
                "bucket_ts": hour_ts,
                "object_dn": s.object_dn,
                "family": s.family,
                "counter_id": s.counter_id,
                "gp_seconds": gp,
                "ne_type": ne,
                "stream": stream,
                "vendor": s.vendor or "nokia",
                "sum_value": 0.0,
                "weight": 0.0,
                "min_value": None,
                "max_value": None,
                "sample_count": 0,
                "value": None,
            }
            slot = out[key]
        if s.value is None:
            continue
        v = float(s.value)
        slot["sum_value"] = float(slot["sum_value"]) + v
        slot["weight"] = float(slot["weight"]) + 1.0
        slot["min_value"] = v if slot["min_value"] is None else min(float(slot["min_value"]), v)
        slot["max_value"] = v if slot["max_value"] is None else max(float(slot["max_value"]), v)
        slot["sample_count"] = int(slot["weight"])
        if s.family:
            slot["family"] = s.family
    return out
