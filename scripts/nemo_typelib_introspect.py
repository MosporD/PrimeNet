"""
Read-only TypeLib introspection for Nemo decoder COM classes.

Extracts interfaces and method names from registered TypeLib GUIDs,
focused on Nemo decoder classes (LayerRRC/LayerRM/Layer3/...).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import winreg
from datetime import UTC, datetime

import comtypes
from comtypes import typeinfo


TARGET_CLASS_NAMES = {
    "L2Decoder Class",
    "L3Decoder Class",
    "LRMDecoder Class",
    "RRCDecoder Class",
    "RRLPDecoder Class",
    "RTPDecoder Class",
    "SNPDecoder Class",
    "LPPDecoder Class",
    "LLCDecoder Class",
    "GANDecoder Class",
    "DecoderProtocol Class",
}


def enum_decoder_classes():
    base = r"SOFTWARE\Classes\CLSID"
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
    rows = []
    i = 0
    while True:
        try:
            clsid = winreg.EnumKey(k, i)
            i += 1
        except OSError:
            break
        try:
            ck = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, base + "\\" + clsid, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY
            )
            name, _ = winreg.QueryValueEx(ck, None)
            name = str(name or "")
        except OSError:
            continue
        if name not in TARGET_CLASS_NAMES:
            continue
        vals = {"dll": "", "progid": "", "typelib": ""}
        for sub, key in (("InprocServer32", "dll"), ("ProgID", "progid"), ("TypeLib", "typelib")):
            try:
                sk = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    base + "\\" + clsid + "\\" + sub,
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
                )
                v, _ = winreg.QueryValueEx(sk, None)
                vals[key] = str(v or "")
            except OSError:
                pass
        rows.append({"name": name, "clsid": clsid, **vals})
    rows.sort(key=lambda x: x["name"])
    return rows


def parse_typelib_versions(tlib_guid: str):
    # Registry path: HKCR\TypeLib\{GUID}\<version>\0\win32
    base = r"TypeLib\\" + tlib_guid
    versions = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, base, 0, winreg.KEY_READ)
    except OSError:
        return versions
    i = 0
    while True:
        try:
            ver = winreg.EnumKey(root, i)
            i += 1
        except OSError:
            break
        m = re.match(r"^([0-9A-Fa-f]+)\.([0-9A-Fa-f]+)$", ver)
        if not m:
            continue
        major = int(m.group(1), 16)
        minor = int(m.group(2), 16)
        versions.append((major, minor, ver))
    versions.sort(reverse=True)
    return versions


def typekind_name(kind: int) -> str:
    mapping = {
        0: "enum",
        1: "record",
        2: "module",
        3: "interface",
        4: "dispatch",
        5: "coclass",
        6: "alias",
        7: "union",
    }
    return mapping.get(int(kind), str(kind))


def inspect_typelib(guid_str: str, major: int, minor: int):
    libid = comtypes.GUID(guid_str)
    tlb = typeinfo.LoadRegTypeLib(libid, major, minor, 0)
    count = tlb.GetTypeInfoCount()
    types = []
    for idx in range(count):
        tinfo = tlb.GetTypeInfo(idx)
        tattr = tinfo.GetTypeAttr()
        kind = typekind_name(tattr.typekind)
        doc_name, doc_string, _help, _helpctx = tlb.GetDocumentation(idx)
        entry = {
            "name": str(doc_name or ""),
            "doc": str(doc_string or ""),
            "typekind": kind,
            "iid": str(tattr.guid),
            "methods": [],
            "impl_types": [],
        }
        if kind in ("interface", "dispatch"):
            for fidx in range(tattr.cFuncs):
                fd = tinfo.GetFuncDesc(fidx)
                names = tinfo.GetNames(fd.memid, 32)
                mname = names[0] if names else f"memid_{fd.memid}"
                entry["methods"].append(
                    {
                        "name": str(mname),
                        "memid": int(fd.memid),
                        "invkind": int(fd.invkind),
                        "callconv": int(fd.callconv),
                        "param_count": int(fd.cParams),
                        "optional_param_count": int(fd.cParamsOpt),
                    }
                )
        elif kind == "coclass":
            for impl_idx in range(tattr.cImplTypes):
                href = tinfo.GetRefTypeOfImplType(impl_idx)
                rt = tinfo.GetRefTypeInfo(href)
                rattr = rt.GetTypeAttr()
                rn, rd, _hh, _hc = rt.GetDocumentation(-1)
                entry["impl_types"].append(
                    {
                        "name": str(rn or ""),
                        "doc": str(rd or ""),
                        "iid": str(rattr.guid),
                        "typekind": typekind_name(rattr.typekind),
                    }
                )
        types.append(entry)
    return {
        "guid": guid_str,
        "major": major,
        "minor": minor,
        "type_count": count,
        "types": types,
    }


def main():
    ap = argparse.ArgumentParser(description="Inspect Nemo decoder TypeLib interfaces and methods.")
    ap.add_argument(
        "--out",
        default=os.path.join("uploads", "drive_test_viewer", "nemo_typelib_report.json"),
        help="Output JSON path",
    )
    args = ap.parse_args()

    classes = enum_decoder_classes()
    typelib_groups = {}
    for c in classes:
        tg = c.get("typelib")
        if not tg:
            continue
        typelib_groups.setdefault(tg, []).append(c)

    typelibs = []
    for tguid, cls_rows in sorted(typelib_groups.items()):
        versions = parse_typelib_versions(tguid)
        tentry = {
            "typelib_guid": tguid,
            "classes": cls_rows,
            "versions_found": [{"major": a, "minor": b, "raw": r} for a, b, r in versions],
            "loaded": [],
            "errors": [],
        }
        for major, minor, raw in versions[:2]:  # latest two versions at most
            try:
                loaded = inspect_typelib(tguid, major, minor)
                loaded["raw_version"] = raw
                tentry["loaded"].append(loaded)
            except Exception as exc:
                tentry["errors"].append(
                    {"raw_version": raw, "major": major, "minor": minor, "error": str(exc)}
                )
        typelibs.append(tentry)

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "class_count": len(classes),
        "typelib_count": len(typelib_groups),
        "classes": classes,
        "typelibs": typelibs,
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"written: {args.out}")
    print(f"classes: {len(classes)}")
    print(f"typelibs: {len(typelib_groups)}")


if __name__ == "__main__":
    main()

