"""Full structural dump of one Nokia PM .xml.gz file."""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lxml import etree

from core.pm_plus.nokia_parser import parse_file


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def dump(path: Path) -> dict:
    raw = path.read_bytes()
    is_gz = len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B
    xml_bytes = gzip.decompress(raw) if is_gz else raw
    xml_text = xml_bytes.decode("utf-8", errors="replace")

    # Header/footer peek
    head = xml_text[:2500]
    tail = xml_text[-800:] if len(xml_text) > 800 else xml_text

    # Structural walk (lightweight)
    root = etree.fromstring(xml_bytes)
    ns = root.nsmap.get(None) or ""
    file_header = root.find(f".//{{{ns}}}fileHeader") if ns else root.find(".//fileHeader")
    file_footer = root.find(f".//{{{ns}}}fileFooter") if ns else root.find(".//fileFooter")
    me = root.find(f".//{{{ns}}}managedElement") if ns else root.find(".//managedElement")

    families: list[dict] = []
    tag_meas_info = f"{{{ns}}}measInfo" if ns else "measInfo"
    for mi in root.iter(tag_meas_info):
        fam = (mi.get("measInfoId") or "").strip()
        gp = None
        types: list[str] = []
        classic_types: dict[str, str] = {}
        objects: list[str] = []
        result_lens: list[int] = []
        layout = "unknown"

        for child in mi:
            t = _local(child.tag)
            if t == "granPeriod":
                gp = {
                    "duration": child.get("duration"),
                    "endTime": child.get("endTime"),
                }
            elif t == "measTypes":
                types = [x for x in (child.text or "").split() if x]
                layout = "nokia_compact"
            elif t == "measType":
                classic_types[child.get("p") or ""] = (child.text or "").strip()
                layout = "classic_3gpp"
            elif t == "measValue":
                objects.append((child.get("measObjLdn") or "").strip())
                for gc in child:
                    if _local(gc.tag) == "measResults":
                        result_lens.append(len((gc.text or "").split()))
                    elif _local(gc.tag) == "r":
                        result_lens.append(1)

        if classic_types and not types:
            types = [classic_types[k] for k in sorted(classic_types, key=lambda x: int(x) if x.isdigit() else x)]

        families.append(
            {
                "measInfoId": fam,
                "layout": layout,
                "granPeriod": gp,
                "counter_count": len(types),
                "counters": types,
                "object_count": len(objects),
                "objects_sample": objects[:8],
                "all_objects": objects,
                "measResults_token_counts": {
                    "min": min(result_lens) if result_lens else 0,
                    "max": max(result_lens) if result_lens else 0,
                    "unique": sorted(set(result_lens)),
                },
                "matrix_cells": len(types) * len(objects),
            }
        )

    parsed = parse_file(path)
    value_stats = Counter()
    nilish = 0
    numeric = 0
    by_family_samples = Counter()
    sample_rows = []
    for i, s in enumerate(parsed.samples):
        by_family_samples[s.family] += 1
        if s.value is None:
            nilish += 1
            value_stats["null"] += 1
        else:
            numeric += 1
            if s.value == 0:
                value_stats["zero"] += 1
            else:
                value_stats["nonzero"] += 1
        if i < 25:
            sample_rows.append(
                {
                    "bucket_ts": s.bucket_ts,
                    "family": s.family,
                    "object_dn": s.object_dn,
                    "counter_id": s.counter_id,
                    "value": s.value,
                    "gp_seconds": s.gp_seconds,
                    "managed_element": s.managed_element,
                }
            )

    # One full object × family matrix example (first family, first object)
    matrix_example = None
    if families and families[0]["counters"] and families[0]["all_objects"]:
        fam0 = families[0]["measInfoId"]
        obj0 = families[0]["all_objects"][0]
        pairs = [
            {"counter_id": s.counter_id, "value": s.value}
            for s in parsed.samples
            if s.family == fam0 and s.object_dn == obj0
        ]
        matrix_example = {
            "family": fam0,
            "object_dn": obj0,
            "cells": pairs,
            "cell_count": len(pairs),
        }

    tree_tags = Counter(_local(e.tag) for e in root.iter())

    return {
        "file": {
            "path": str(path),
            "name": path.name,
            "compressed_bytes": len(raw),
            "uncompressed_bytes": len(xml_bytes),
            "compression_ratio": round(len(xml_bytes) / max(1, len(raw)), 2),
            "is_gzip": is_gz,
            "xml_chars": len(xml_text),
            "xml_lines": xml_text.count("\n") + 1,
        },
        "envelope": {
            "root_tag": _local(root.tag),
            "xmlns": ns,
            "fileHeader_attrs": dict(file_header.attrib) if file_header is not None else {},
            "managedElement_attrs": dict(me.attrib) if me is not None else {},
            "fileFooter_attrs": dict(file_footer.attrib) if file_footer is not None else {},
            "element_tag_counts": dict(tree_tags.most_common()),
        },
        "xml_head": head,
        "xml_tail": tail,
        "summary": {
            "measInfo_blocks": len(families),
            "unique_families": sorted({f["measInfoId"] for f in families}),
            "total_objects_across_blocks": sum(f["object_count"] for f in families),
            "unique_object_dns": len(parsed.objects),
            "unique_counters": len(parsed.counters),
            "total_samples_parsed": len(parsed.samples),
            "numeric_values": numeric,
            "null_or_nil_values": nilish,
            "value_breakdown": dict(value_stats),
            "samples_per_family": dict(by_family_samples),
            "managed_element": parsed.managed_element,
            "bucket_hint": parsed.file_begin,
        },
        "families": [
            {k: v for k, v in f.items() if k != "all_objects"}  # keep report readable
            for f in families
        ],
        "matrix_example_one_object": matrix_example,
        "sample_rows_first_25": sample_rows,
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "raw/pm_plus/_debug/PM202609111231+030072MRBTS_-_1.xml.gz"
    )
    out = dump(path)
    # Also write pretty JSON next to the gz for browsing
    out_path = path.with_suffix(path.suffix + ".breakdown.json")
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("file", "envelope", "summary")}, indent=2))
    print(f"\n--- full breakdown written to ---\n{out_path}")
    print("\n=== XML HEAD ===\n")
    print(out["xml_head"])
    print("\n=== FAMILIES (compact) ===\n")
    for f in out["families"]:
        print(
            f"- {f['measInfoId']}: layout={f['layout']} counters={f['counter_count']} "
            f"objects={f['object_count']} cells={f['matrix_cells']} gp={f['granPeriod']}"
        )
        print(f"  counters: {', '.join(f['counters'][:40])}{' ...' if len(f['counters']) > 40 else ''}")
        print(f"  objects sample: {f['objects_sample']}")
    if out.get("matrix_example_one_object"):
        mx = out["matrix_example_one_object"]
        print(f"\n=== FULL MATRIX: {mx['family']} @ {mx['object_dn']} ({mx['cell_count']} cells) ===\n")
        for cell in mx["cells"]:
            print(f"  {cell['counter_id']:>24} = {cell['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
