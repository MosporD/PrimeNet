"""
Probe private COM interfaces (IIDs) exposed by Nemo decoder objects.

Approach:
- Create decoder COM object by ProgID (32-bit Python required).
- Extract GUID-like strings from the corresponding decoder DLL.
- Attempt QueryInterface against each GUID as an empty IUnknown-derived interface.
- Report which IIDs are accepted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import winreg
from datetime import UTC, datetime

import comtypes
import comtypes.client


TARGETS = {
    "Layer2.L2Decoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\Layer2.dll",
    "Layer3.L3Decoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\Layer3.dll",
    "LayerRM.LRMDecoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\LayerRM.dll",
    "LayerRRC.RRCDecoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\LayerRRC.dll",
    "LayerRRLP.RRLPDecoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\LayerRRLP.dll",
    "LayerRTP.RTPDecoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\LayerRTP.dll",
    "LayerSNP.SNPDecoder.1": r"C:\Program Files (x86)\Anite\Nemo Outdoor\LayerSNP.dll",
}


def guids_from_dll(path: str):
    if not os.path.exists(path):
        return []
    b = open(path, "rb").read()
    vals = sorted(set(m.group(0).decode("ascii") for m in re.finditer(rb"\{[0-9A-Fa-f\-]{36}\}", b)))
    return vals


def typelibs_for_progid(progid: str):
    # Look up CLSID and TypeLib hints in registry.
    out = []
    try:
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID")
        clsid, _ = winreg.QueryValueEx(k, None)
    except OSError:
        return out
    try:
        tk = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\TypeLib")
        tguid, _ = winreg.QueryValueEx(tk, None)
        out.append(str(tguid))
    except OSError:
        pass
    return out


def make_iface(iid_str: str):
    return type(
        f"IProbe_{iid_str.strip('{}').replace('-', '_')}",
        (comtypes.IUnknown,),
        {"_iid_": comtypes.GUID(iid_str), "_methods_": []},
    )


def probe_progid(progid: str, dll_path: str):
    row = {
        "progid": progid,
        "dll": dll_path,
        "create_success": False,
        "candidate_iids": [],
        "supported_iids": [],
        "errors": [],
    }
    candidates = set()
    for g in guids_from_dll(dll_path):
        candidates.add(g)
    for g in typelibs_for_progid(progid):
        candidates.add(g)
    row["candidate_iids"] = sorted(candidates)
    try:
        obj = comtypes.client.CreateObject(progid, dynamic=False)
        row["create_success"] = True
    except Exception as exc:
        row["errors"].append(f"CreateObject: {exc}")
        return row

    for iid in row["candidate_iids"]:
        try:
            iface = make_iface(iid)
            _ = obj.QueryInterface(iface)
            row["supported_iids"].append(iid)
        except Exception:
            continue
    return row


def main():
    ap = argparse.ArgumentParser(description="Probe Nemo decoder private IIDs.")
    ap.add_argument(
        "--out",
        default=os.path.join("uploads", "drive_test_viewer", "nemo_iid_probe_report.json"),
        help="Output JSON path",
    )
    args = ap.parse_args()

    results = []
    for progid, dll in TARGETS.items():
        results.append(probe_progid(progid, dll))

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "target_count": len(TARGETS),
        "results": results,
    }
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"written: {args.out}")
    for r in results:
        print(
            f"{r['progid']} | created={r['create_success']} | candidates={len(r['candidate_iids'])} | supported={len(r['supported_iids'])}"
        )


if __name__ == "__main__":
    main()

