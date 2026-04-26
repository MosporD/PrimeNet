"""
Read-only DLL recon helper for Nemo decoder modules.

Usage:
  python scripts/nemo_dll_recon.py --dll "C:\\Program Files\\Anite\\Nemo Analyze\\Loader\\Decoders\\LayerRM.dll"
  python scripts/nemo_dll_recon.py --dll-dir "C:\\Program Files\\Anite\\Nemo Analyze\\Loader\\Decoders"
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, UTC

import pefile

KEYWORDS = (
    "RSRP",
    "RSRQ",
    "RSCP",
    "ECNO",
    "EcNo",
    "SINR",
    "CQI",
    "LTE",
    "NR",
    "UMTS",
    "GSM",
    "CELLMEAS",
    "MIMO",
    "RRC",
    "NAS",
    "MAC",
    "RLC",
    "PHY",
    "decode",
    "parser",
    "measurement",
)


def extract_ascii_strings(blob: bytes, min_len: int = 6) -> list[str]:
    rx = re.compile(rb"[ -~]{%d,}" % min_len)
    return [m.group(0).decode("ascii", errors="ignore") for m in rx.finditer(blob)]


def analyze_dll(path: str) -> dict:
    result: dict = {
        "path": path,
        "exists": os.path.exists(path),
        "size_bytes": None,
        "machine": None,
        "timestamp_utc": None,
        "image_base": None,
        "entry_point": None,
        "sections": [],
        "imports": [],
        "exports": [],
        "keyword_hits": {},
        "keyword_strings_preview": {},
        "errors": [],
    }
    if not result["exists"]:
        result["errors"].append("file_not_found")
        return result

    try:
        data = open(path, "rb").read()
        result["size_bytes"] = len(data)
        pe = pefile.PE(data=data, fast_load=False)
        pe.parse_data_directories()
        result["machine"] = hex(pe.FILE_HEADER.Machine)
        result["timestamp_utc"] = datetime.fromtimestamp(
            pe.FILE_HEADER.TimeDateStamp, UTC
        ).isoformat().replace("+00:00", "Z")
        result["image_base"] = hex(pe.OPTIONAL_HEADER.ImageBase)
        result["entry_point"] = hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint)

        for sec in pe.sections:
            result["sections"].append(
                {
                    "name": sec.Name.decode("ascii", errors="ignore").rstrip("\x00"),
                    "virtual_address": hex(sec.VirtualAddress),
                    "virtual_size": int(sec.Misc_VirtualSize),
                    "raw_size": int(sec.SizeOfRawData),
                    "entropy": round(float(sec.get_entropy()), 3),
                }
            )

        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for imp_desc in pe.DIRECTORY_ENTRY_IMPORT:
                dll_name = (
                    imp_desc.dll.decode("ascii", errors="ignore")
                    if imp_desc.dll
                    else "unknown"
                )
                funcs = []
                for imp in imp_desc.imports:
                    if imp.name:
                        funcs.append(imp.name.decode("ascii", errors="ignore"))
                    elif imp.ordinal:
                        funcs.append(f"ordinal:{imp.ordinal}")
                result["imports"].append({"dll": dll_name, "functions": funcs[:120]})

        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                nm = exp.name.decode("ascii", errors="ignore") if exp.name else ""
                result["exports"].append(
                    {"name": nm or None, "ordinal": exp.ordinal, "address": hex(exp.address)}
                )

        all_strings = extract_ascii_strings(data, min_len=6)
        upper_strings = [(s, s.upper()) for s in all_strings]
        for k in KEYWORDS:
            ku = k.upper()
            hits = [s for s, su in upper_strings if ku in su]
            result["keyword_hits"][k] = len(hits)
            if hits:
                result["keyword_strings_preview"][k] = hits[:20]

    except Exception as exc:  # pragma: no cover - defensive for unknown PE variants
        result["errors"].append(str(exc))
    return result


def collect_targets(single_dll: str | None, dll_dir: str | None) -> list[str]:
    targets: list[str] = []
    if single_dll:
        targets.append(single_dll)
    if dll_dir and os.path.isdir(dll_dir):
        for name in sorted(os.listdir(dll_dir)):
            if name.lower().endswith(".dll"):
                targets.append(os.path.join(dll_dir, name))
    deduped = []
    seen = set()
    for t in targets:
        n = os.path.normcase(os.path.normpath(t))
        if n in seen:
            continue
        seen.add(n)
        deduped.append(t)
    return deduped


def collect_targets_recursive(root_dir: str | None) -> list[str]:
    if not root_dir or not os.path.isdir(root_dir):
        return []
    out: list[str] = []
    for cur, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith(".dll"):
                out.append(os.path.join(cur, name))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser(description="Recon Nemo decoder DLLs (read-only).")
    ap.add_argument("--dll", help="Full path to one DLL file")
    ap.add_argument("--dll-dir", help="Directory containing DLLs")
    ap.add_argument("--root-dir", help="Recursively scan DLLs from root directory")
    ap.add_argument(
        "--out",
        help="Output JSON path",
        default=os.path.join("uploads", "drive_test_viewer", "nemo_dll_recon_report.json"),
    )
    args = ap.parse_args()

    targets = collect_targets(args.dll, args.dll_dir) + collect_targets_recursive(args.root_dir)
    if not targets:
        raise SystemExit("No DLL targets. Use --dll or --dll-dir.")

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "target_count": len(targets),
        "targets": targets,
        "results": [analyze_dll(t) for t in targets],
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"written: {args.out}")
    print(f"analyzed_dlls: {len(targets)}")


if __name__ == "__main__":
    main()

