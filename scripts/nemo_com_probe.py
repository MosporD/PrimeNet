"""
Read-only COM probe for Nemo decoder classes.

This script:
1) Reads CLSID registrations from registry for decoder-like classes.
2) Attempts CoCreateInstance with IUnknown only (no method invocation).
3) Writes a probe report JSON.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import winreg
from datetime import UTC, datetime


CLSCTX_INPROC_SERVER = 0x1

IID_IUNKNOWN = ctypes.c_byte * 16
IID_IUnknown = IID_IUNKNOWN(
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0xC0,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x46,
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def parse_guid(clsid: str) -> GUID:
    s = clsid.strip().strip("{}")
    parts = s.split("-")
    if len(parts) != 5:
        raise ValueError(f"Invalid CLSID: {clsid}")
    d1 = int(parts[0], 16)
    d2 = int(parts[1], 16)
    d3 = int(parts[2], 16)
    tail = bytes.fromhex(parts[3] + parts[4])
    g = GUID()
    g.Data1 = d1
    g.Data2 = d2
    g.Data3 = d3
    g.Data4[:] = tail
    return g


def reg_candidates() -> list[dict]:
    rows = []
    bases = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\CLSID", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\CLSID", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_CLASSES_ROOT, r"CLSID", 0),
    ]
    seen = set()
    for root, base, view in bases:
        try:
            k = winreg.OpenKey(root, base, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        i = 0
        while True:
            try:
                clsid = winreg.EnumKey(k, i)
                i += 1
            except OSError:
                break
            if clsid in seen:
                continue
            seen.add(clsid)
            try:
                ck = winreg.OpenKey(root, base + "\\" + clsid, 0, winreg.KEY_READ | view)
                name, _ = winreg.QueryValueEx(ck, None)
            except OSError:
                name = ""
            try:
                ik = winreg.OpenKey(
                    root, base + "\\" + clsid + "\\InprocServer32", 0, winreg.KEY_READ | view
                )
                dll, _ = winreg.QueryValueEx(ik, None)
            except OSError:
                continue
            name_s = str(name or "")
            dll_s = str(dll or "")
            if not dll_s:
                continue
            # Focus decoder-related classes.
            if re.search(r"(Decoder|Layer[0-9A-Za-z]+)", name_s, re.I) or re.search(
                r"\\Layer[0-9A-Za-z]+\.dll$", dll_s, re.I
            ):
                rows.append({"clsid": clsid, "name": name_s, "dll": dll_s})
    rows.sort(key=lambda r: (r["dll"].lower(), r["name"].lower(), r["clsid"].lower()))
    return rows


def probe_cocreate(clsid: str) -> tuple[bool, int, str]:
    ole32 = ctypes.windll.ole32
    ptr = ctypes.c_void_p()
    rclsid = parse_guid(clsid)
    hr = ole32.CoCreateInstance(
        ctypes.byref(rclsid),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_IUnknown),
        ctypes.byref(ptr),
    )
    ok = hr == 0 and bool(ptr.value)
    if ptr.value:
        # Release IUnknown (vtable[2] = Release)
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)(vtbl[2])
        release(ptr)
    return ok, int(hr), hex(ctypes.c_uint32(hr).value)


def main():
    ap = argparse.ArgumentParser(description="Probe Nemo decoder COM CLSIDs.")
    ap.add_argument(
        "--out",
        default=os.path.join("uploads", "drive_test_viewer", "nemo_com_probe_report.json"),
        help="Output JSON path",
    )
    args = ap.parse_args()

    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    try:
        candidates = reg_candidates()
        results = []
        for row in candidates:
            ok, hr, hr_hex = probe_cocreate(row["clsid"])
            results.append(
                {
                    **row,
                    "cocreate_success": ok,
                    "hresult": hr,
                    "hresult_hex": hr_hex,
                }
            )
        report = {
            "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "candidate_count": len(candidates),
            "success_count": sum(1 for r in results if r["cocreate_success"]),
            "results": results,
        }
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"written: {args.out}")
        print(f"candidates: {len(candidates)}")
        print(f"success: {report['success_count']}")
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    main()

