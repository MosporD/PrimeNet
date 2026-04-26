"""
Runtime COM dispatch/typeinfo introspection for Nemo decoder classes.

Attempts:
1) Create COM object by ProgID (where available)
2) Query IDispatch
3) Pull method/property names from GetTypeInfo / ITypeInfo
"""

from __future__ import annotations

import argparse
import json
import os
import winreg
from datetime import UTC, datetime

import comtypes
import comtypes.client
from comtypes.automation import IDispatch


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


def enum_classes():
    base = r"SOFTWARE\Classes\CLSID"
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
    out = []
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
        progid = ""
        dll = ""
        try:
            pk = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                base + "\\" + clsid + "\\ProgID",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            )
            progid, _ = winreg.QueryValueEx(pk, None)
        except OSError:
            pass
        try:
            dk = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                base + "\\" + clsid + "\\InprocServer32",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            )
            dll, _ = winreg.QueryValueEx(dk, None)
        except OSError:
            pass
        out.append({"name": name, "clsid": clsid, "progid": str(progid or ""), "dll": str(dll or "")})
    out.sort(key=lambda r: r["name"])
    return out


def inspect_dispatch(obj):
    info = {
        "idispatch": False,
        "typeinfo_count": None,
        "members": [],
        "errors": [],
    }
    try:
        disp = obj.QueryInterface(IDispatch)
        info["idispatch"] = True
    except Exception as exc:
        info["errors"].append(f"QueryInterface(IDispatch): {exc}")
        return info

    try:
        cnt = disp.GetTypeInfoCount()
        info["typeinfo_count"] = int(cnt)
    except Exception as exc:
        info["errors"].append(f"GetTypeInfoCount: {exc}")
        return info

    if not info["typeinfo_count"]:
        return info

    try:
        ti = disp.GetTypeInfo(0)
        ta = ti.GetTypeAttr()
        for idx in range(int(ta.cFuncs)):
            try:
                fd = ti.GetFuncDesc(idx)
                names = ti.GetNames(fd.memid, 32)
                if names:
                    info["members"].append(
                        {
                            "name": str(names[0]),
                            "memid": int(fd.memid),
                            "invkind": int(fd.invkind),
                            "param_count": int(fd.cParams),
                        }
                    )
            except Exception:
                continue
    except Exception as exc:
        info["errors"].append(f"GetTypeInfo parse: {exc}")
    return info


def main():
    ap = argparse.ArgumentParser(description="Runtime IDispatch introspection for Nemo decoders.")
    ap.add_argument(
        "--out",
        default=os.path.join("uploads", "drive_test_viewer", "nemo_dispatch_report.json"),
        help="Output JSON path",
    )
    args = ap.parse_args()

    classes = enum_classes()
    results = []
    for c in classes:
        row = dict(c)
        row["create_success"] = False
        row["dispatch"] = {}
        row["error"] = ""
        progid = c.get("progid") or ""
        if not progid:
            row["error"] = "no_progid"
            results.append(row)
            continue
        try:
            obj = comtypes.client.CreateObject(progid, dynamic=False)
            row["create_success"] = True
            row["dispatch"] = inspect_dispatch(obj)
        except Exception as exc:
            row["error"] = str(exc)
        results.append(row)

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "class_count": len(classes),
        "create_success_count": sum(1 for r in results if r["create_success"]),
        "idispatch_count": sum(1 for r in results if r.get("dispatch", {}).get("idispatch")),
        "results": results,
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"written: {args.out}")
    print(f"classes: {report['class_count']}")
    print(f"create_success: {report['create_success_count']}")
    print(f"idispatch: {report['idispatch_count']}")


if __name__ == "__main__":
    main()

