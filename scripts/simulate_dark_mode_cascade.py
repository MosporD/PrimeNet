#!/usr/bin/env python3
"""Terminal simulation: dark-mode cascade wins + blueprint template wiring."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def has_important_for(css: str, selector: str) -> bool:
    for m in re.finditer(r"body\.dark-mode[^{]+\{[^}]+\}", css, re.S):
        block = m.group(0)
        if selector in block and "!important" in block:
            return True
    return False


def main() -> int:
    final = (ROOT / "static/css/theme-dark-final.css").read_text(encoding="utf-8")
    common = (ROOT / "static/css/common.css").read_text(encoding="utf-8")
    js = (ROOT / "static/js/common.js").read_text(encoding="utf-8")

    print("=== Simulate theme toggle assets ===")
    print(
        "  PASS inject"
        if "_ensureDarkThemeFinalStylesheet" in js and "theme-dark-final.css" in js
        else "  FAIL inject"
    )

    checks = [
        (".btn-primary", "primary button"),
        (".btn-secondary", "secondary button"),
        (".data-table th", "table header"),
        (".data-table td", "table cell"),
        (".tech-chip", "tech chip"),
        (".cd-tab", "dashboard tab"),
        (".sankey-wrap", "sankey surface"),
        (".adj-filter-panel", "adjacency filter"),
        (".opt-panel", "opt-cases panel"),
        (".field-label", "field label"),
    ]
    print("=== Simulate dark cascade (!important wins over module CSS) ===")
    failed = 0
    for sel, label in checks:
        ok = has_important_for(final, sel) or has_important_for(common, sel)
        print(f"  {'PASS' if ok else 'FAIL'}: {label} ({sel})")
        if not ok:
            failed += 1

    span_flat = bool(
        re.search(
            r"body\.dark-mode[^{]*\bspan\b[^{]*\{[^}]*color:[^}]*!important",
            common,
            re.S,
        )
    )
    print(
        f"  {'FAIL' if span_flat else 'PASS'}: no blanket span color flatten in common.css"
    )
    if span_flat:
        failed += 1

    print("=== Blueprint page templates (common.js + common.css) ===")
    for routes in sorted((ROOT / "modules").glob("*/routes.py")):
        mod = routes.parent.name
        tdir = routes.parent / "templates"
        if not tdir.is_dir():
            print(f"  SKIP {mod}: no templates/")
            continue
        pages = []
        for t in sorted(tdir.glob("*.html")):
            text = t.read_text(encoding="utf-8", errors="ignore")
            if "<!DOCTYPE" in text or "<html" in text.lower():
                pages.append((t.name, text))
        if not pages:
            print(f"  SKIP {mod}: no standalone HTML (extends/partial only)")
            continue
        bad = []
        for name, text in pages:
            if "common.js" not in text:
                bad.append(f"{name}: missing common.js")
            if "common.css" not in text:
                bad.append(f"{name}: missing common.css")
        if bad:
            print(f"  FAIL {mod}: {'; '.join(bad)}")
            failed += 1
        else:
            print(f"  PASS {mod} ({len(pages)} page(s))")

    print()
    print("OVERALL", "PASS" if failed == 0 else f"FAIL ({failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
